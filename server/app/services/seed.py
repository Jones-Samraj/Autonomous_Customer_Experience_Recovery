"""Reference data, demo users and the simulated demo dataset (loaded through the normal ingestion pipeline)."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import ALL_ROLES, hash_password
from app.db import utcnow
from app.models import CustomerSignal, Role, User
from app.services import ingestion
from app.services.kpis import ensure_kpis, persist_history
from app.services.system import get_setting, set_setting, set_sim_now
from app.sim.ground_truth import build_ground_truth
from app.sim.world import SEGMENTS, World, default_state, make_customers

log = logging.getLogger("cx.seed")

ROLE_DESC = {"viewer": "Read-only access to dashboards", "analyst": "Run analyses, upload data, use the jury simulator",
             "approver": "Approve or reject consequential interventions", "admin": "Full access including data retention and reset"}
DEMO_USERS = [("admin@cxsentinel.ai", "Avery Admin", "admin"), ("analyst@cxsentinel.ai", "Ana Analyst", "analyst"),
              ("approver@cxsentinel.ai", "Ari Approver", "approver"), ("viewer@cxsentinel.ai", "Val Viewer", "viewer")]
LOAD_ORDER = [("customer_segments", "customer_segments.csv"), ("customers", "customers.csv"), ("release_history", "release_history.csv"),
              ("operational_events", "operational_events.csv"), ("customer_reviews", "customer_reviews.csv"),
              ("support_tickets", "support_tickets.csv"), ("social_feedback", "social_feedback.csv"),
              ("survey_responses", "survey_responses.csv"), ("transactions", "transactions.csv"),
              ("product_telemetry", "product_telemetry.csv"), ("operational_metrics", "operational_metrics.csv")]
FRAME_FILE = {"reviews": "customer_reviews.csv", "tickets": "support_tickets.csv", "social": "social_feedback.csv",
              "surveys": "survey_responses.csv", "transactions": "transactions.csv", "telemetry": "product_telemetry.csv",
              "metrics": "operational_metrics.csv", "events": "operational_events.csv", "releases": "release_history.csv"}


def ensure_reference_data(db: Session) -> None:
    s = get_settings()
    roles = {r.name: r for r in db.scalars(select(Role))}
    for name in ALL_ROLES:
        if name not in roles:
            roles[name] = Role(name=name, description=ROLE_DESC[name])
            db.add(roles[name])
    db.flush()
    have = {u.email for u in db.scalars(select(User))}
    for email, full, role in DEMO_USERS:
        if email not in have and s.demo_mode:
            db.add(User(email=email, full_name=full, hashed_password=hash_password(s.demo_password), role_id=roles[role].id))
    ensure_kpis(db)
    db.flush()


def _dump(df: pd.DataFrame, path: Path) -> None:
    df = df.copy()
    for c in df.columns:
        if df[c].map(lambda x: isinstance(x, dict)).any():
            df[c] = df[c].map(lambda x: json.dumps(x) if isinstance(x, dict) else x)
    df.to_csv(path, index=False)


def generate_samples(anchor: datetime, seed: int = 7) -> dict:
    """Write simulated sample CSVs (uploadable through the UI) and the hidden benchmark ground truth."""
    s = get_settings()
    out = Path(s.data_dir) / "samples"
    bench = Path(s.data_dir) / "benchmark"
    out.mkdir(parents=True, exist_ok=True)
    bench.mkdir(parents=True, exist_ok=True)
    customers = make_customers(seed=seed)
    state = default_state(anchor, seed)
    frames = World(state, customers).export(anchor)
    for key, fname in FRAME_FILE.items():
        _dump(frames[key], out / fname)
    _dump(customers, out / "customers.csv")
    _dump(pd.DataFrame([{"segment_code": c, "name": n, "description": d, "rule": r} for c, n, d, r in SEGMENTS]), out / "customer_segments.csv")
    (out / "manifest.json").write_text(json.dumps({"simulated": True, "label": "SIMULATED DATA - not real customers", "anchor": anchor.isoformat(),
                                                   "seed": seed, "generated_at": utcnow().isoformat(),
                                                   "files": {k: len(v) for k, v in frames.items()}}, indent=2))
    (bench / "ground_truth.json").write_text(json.dumps(build_ground_truth(state), indent=2))
    return {"anchor": anchor.isoformat(), "state": state}


def _anchor_from_manifest() -> datetime | None:
    m = Path(get_settings().data_dir) / "samples" / "manifest.json"
    if m.exists():
        try:
            return datetime.fromisoformat(json.loads(m.read_text())["anchor"])
        except (KeyError, ValueError):
            return None
    return None


def load_samples(db: Session, user_id: int | None = None) -> dict:
    d = Path(get_settings().data_dir) / "samples"
    reports = {}
    for dtype, fname in LOAD_ORDER:
        path = d / fname
        if not path.exists():
            continue
        df = ingestion.read_upload(path.read_bytes(), fname)
        reports[dtype] = ingestion.ingest(db, dtype, df, source_name=f"{ingestion.DATASETS[dtype]['label']} (simulated)", user_id=user_id,
                                          is_simulated=True, file_name=fname)
    return reports


def seed_demo(db: Session) -> dict | None:
    """Load the simulated dataset once. Returns ingestion reports, or None when data already exists."""
    s = get_settings()
    ensure_reference_data(db)
    db.commit()
    if not s.seed_demo_data or db.scalar(select(func.count()).select_from(CustomerSignal)):
        return None
    anchor = _anchor_from_manifest()
    manifest = Path(s.data_dir) / "samples" / "manifest.json"
    if anchor is None or not manifest.exists():
        now = utcnow()
        anchor = datetime(now.year, now.month, now.day)
        generate_samples(anchor)
    seed = json.loads(manifest.read_text()).get("seed", 7) if manifest.exists() else 7
    set_setting(db, "world_state", default_state(anchor, seed))
    set_sim_now(db, anchor)
    reports = load_samples(db)
    from app.agents.context import Ctx

    ctx = Ctx(db, "seed")
    persist_history(db, ctx.view)
    db.commit()
    log.info("Seeded simulated demo data: %s", {k: v["inserted"] for k, v in reports.items()})
    return reports
