from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import analyst
from app.api.serializers import signal_out
from app.core.config import get_settings
from app.core.security import get_current_user
from app.db import get_db
from app.models import CustomerSignal, DataSource, User
from app.schemas import SignalRecords
from app.services import ingestion, nlp, seed
from app.services.system import audit, get_sim_now

router = APIRouter(tags=["Data & Signals"])


@router.get("/data/datasets", summary="Supported dataset types and their required columns")
def datasets(_: User = Depends(get_current_user)):
    return [{"type": k, "label": v["label"], "source_type": v["source_type"], "required_columns": v["required"], "default_reliability": v["reliability"]}
            for k, v in ingestion.DATASETS.items()]


@router.get("/data/sources", summary="Connected data sources with reliability and volumes")
def sources(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    counts = dict(db.execute(select(CustomerSignal.source_id, func.count()).where(CustomerSignal.is_current.is_(True)).group_by(CustomerSignal.source_id)).all())
    out = []
    for s in db.scalars(select(DataSource).order_by(DataSource.id)):
        out.append({"id": s.id, "name": s.name, "source_type": s.source_type, "reliability": s.reliability, "is_simulated": s.is_simulated, "file_name": s.file_name,
                    "records": counts.get(s.id, s.record_count or 0), "rejected": s.rejected_count, "status": s.status, "last_ingested_at": s.last_ingested_at.isoformat() if s.last_ingested_at else None})
    return out


@router.post("/data/upload", summary="Upload a CSV/XLSX file: validate (dry run) or ingest")
async def upload(file: UploadFile = File(...), dataset_type: str | None = Form(default=None), dry_run: bool = Form(default=True), source_name: str | None = Form(default=None),
                 db: Session = Depends(get_db), user: User = Depends(analyst)):
    content = await file.read()
    try:
        df = ingestion.read_upload(content, file.filename or "upload.csv")
        dtype = dataset_type or ingestion.detect_dataset_type(df.columns)
        if not dtype:
            raise ValueError("Could not detect the dataset type from the columns; select it explicitly")
        report = ingestion.ingest(db, dtype, df, source_name=source_name, user_id=user.id, is_simulated=False, file_name=file.filename, dry_run=dry_run)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    report["file_name"] = file.filename
    report["detected_type"] = dtype
    if not dry_run:
        audit(db, user.id, "data.upload", "data_source", report.get("source_id"), {k: report[k] for k in ("dataset_type", "accepted", "inserted", "revised", "rejected")})
        db.commit()
    return report


@router.post("/signals/ingest", summary="Ingest a batch of records as JSON")
def ingest_json(body: SignalRecords, db: Session = Depends(get_db), user: User = Depends(analyst)):
    import pandas as pd

    try:
        df = pd.DataFrame(body.records).astype(str)
        report = ingestion.ingest(db, body.dataset_type, df, source_name=body.source_name, user_id=user.id)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    audit(db, user.id, "signals.ingest", "data_source", report.get("source_id"), {"inserted": report["inserted"], "rejected": report["rejected"]})
    db.commit()
    return report


@router.get("/data/samples", summary="Simulated sample datasets that can be uploaded")
def list_samples(_: User = Depends(get_current_user)):
    d = Path(get_settings().data_dir) / "samples"
    names = {v for _, v in seed.LOAD_ORDER}
    return [{"name": p.name, "size_kb": round(p.stat().st_size / 1024, 1), "dataset_type": next((k for k, v in seed.LOAD_ORDER if v == p.name), None), "simulated": True}
            for p in sorted(d.glob("*.csv")) if p.name in names] if d.exists() else []


@router.get("/data/samples/{name}", summary="Download a simulated sample dataset")
def download_sample(name: str, _: User = Depends(get_current_user)):
    p = Path(get_settings().data_dir) / "samples" / Path(name).name
    if not p.exists() or p.suffix != ".csv":
        raise HTTPException(404, "Sample not found")
    return FileResponse(p, media_type="text/csv", filename=p.name)


@router.post("/data/load-samples", summary="Load the simulated sample datasets through the ingestion pipeline (idempotent)")
def load_samples(db: Session = Depends(get_db), user: User = Depends(analyst)):
    from app.services import world_sync
    from app.services.system import get_setting, set_setting, set_sim_now
    from app.sim.world import default_state
    import json

    manifest = Path(get_settings().data_dir) / "samples" / "manifest.json"
    if not manifest.exists():
        seed.generate_samples(datetime(datetime.utcnow().year, datetime.utcnow().month, datetime.utcnow().day))
    m = json.loads(manifest.read_text())
    if not get_setting(db, "world_state"):
        set_setting(db, "world_state", default_state(datetime.fromisoformat(m["anchor"]), m.get("seed", 7)))
        set_sim_now(db, datetime.fromisoformat(m["anchor"]))
    reports = seed.load_samples(db, user.id)
    from app.agents.context import Ctx
    from app.services.kpis import persist_history

    persist_history(db, Ctx(db, "samples").view)
    audit(db, user.id, "data.load_samples", "system", None, {k: v["inserted"] for k, v in reports.items()})
    db.commit()
    _ = world_sync
    return {k: {"received": v["received"], "inserted": v["inserted"], "unchanged": v["unchanged"], "rejected": v["rejected"], "flagged_injection": v["flagged_injection"]}
            for k, v in reports.items()}


@router.get("/signals", summary="Search and filter normalised evidence")
def list_signals(q: str | None = None, source_type: str | None = None, aspect: str | None = None, region: str | None = None, segment: str | None = None,
                 flagged: bool | None = None, injected: bool | None = None, date_from: str | None = None, date_to: str | None = None,
                 page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=200), db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    cond = [CustomerSignal.is_current.is_(True)]
    if q:
        cond.append(or_(CustomerSignal.text.ilike(f"%{q}%"), CustomerSignal.external_id.ilike(f"%{q}%"), CustomerSignal.product.ilike(f"%{q}%")))
    if source_type:
        cond.append(CustomerSignal.source_type == source_type)
    if aspect:
        cond.append(CustomerSignal.primary_aspect == aspect)
    if region:
        cond.append(CustomerSignal.region == region)
    if segment:
        cond.append(CustomerSignal.segment == segment)
    if flagged is not None:
        cond.append(CustomerSignal.is_flagged.is_(flagged))
    if injected is not None:
        cond.append(CustomerSignal.is_injected.is_(injected))
    try:
        if date_from:
            cond.append(CustomerSignal.occurred_at >= datetime.fromisoformat(date_from))
        if date_to:
            cond.append(CustomerSignal.occurred_at <= datetime.fromisoformat(date_to))
    except ValueError:
        raise HTTPException(422, "Invalid date filter")
    total = db.scalar(select(func.count()).select_from(CustomerSignal).where(*cond)) or 0
    rows = db.scalars(select(CustomerSignal).where(*cond).order_by(CustomerSignal.occurred_at.desc()).offset((page - 1) * size).limit(size))
    return {"total": total, "page": page, "size": size, "items": [signal_out(s) for s in rows]}


@router.get("/signals/summary", summary="Evidence volumes by source type and day")
def signals_summary(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    by_type = db.execute(select(CustomerSignal.source_type, func.count(), func.avg(CustomerSignal.reliability)).where(CustomerSignal.is_current.is_(True)).group_by(CustomerSignal.source_type)).all()
    day = func.date(CustomerSignal.occurred_at)
    daily = db.execute(select(day, CustomerSignal.source_type, func.count()).where(CustomerSignal.is_current.is_(True), CustomerSignal.source_type.in_(["review", "ticket", "social", "survey"]))
                       .group_by(day, CustomerSignal.source_type).order_by(day)).all()
    series: dict[str, dict] = {}
    for d, t, n in daily:
        series.setdefault(str(d), {"date": str(d)})[t] = n
    return {"by_type": [{"source_type": t, "count": n, "reliability": round(float(r or 0), 2)} for t, n, r in by_type], "daily_voice": list(series.values()),
            "flagged": db.scalar(select(func.count()).select_from(CustomerSignal).where(CustomerSignal.is_flagged.is_(True), CustomerSignal.is_current.is_(True))) or 0,
            "sim_now": get_sim_now(db).isoformat()}


@router.get("/signals/semantic", summary="Semantic search over customer voice (embeddings)")
def semantic(q: str = Query(min_length=3, max_length=300), k: int = Query(10, ge=1, le=50), db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    clean, _flag, _r = nlp.sanitize_untrusted(q)
    rows = list(db.scalars(select(CustomerSignal).where(CustomerSignal.is_current.is_(True), CustomerSignal.text.is_not(None), CustomerSignal.is_flagged.is_(False),
                                                         CustomerSignal.source_type.in_(["review", "ticket", "social"])).order_by(CustomerSignal.occurred_at.desc()).limit(3000)))
    if not rows:
        return {"backend": None, "items": []}
    emb = nlp.Embedder(get_settings().embedding_backend)
    x = emb.fit_transform([clean] + [r.text for r in rows])
    sims = x[1:] @ x[0]
    idx = np.argsort(-sims)[:k]
    return {"backend": emb.name, "items": [{**signal_out(rows[i]), "similarity": float(sims[i])} for i in idx]}


@router.get("/signals/{signal_id}", summary="One evidence record with all attributes")
def get_signal(signal_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    s = db.get(CustomerSignal, signal_id)
    if s is None:
        raise HTTPException(404, "Signal not found")
    return signal_out(s, full=True)
