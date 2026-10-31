"""Bridge between the simulated world and the platform's ingestion pipeline."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Customer
from app.services import ingestion
from app.services.kpis import persist_history
from app.services.system import get_setting, get_sim_now, set_sim_now
from app.sim.world import World


def has_world(db: Session) -> bool:
    return bool(get_setting(db, "world_state"))


def load_world(db: Session) -> World:
    state = get_setting(db, "world_state")
    if not state:
        raise RuntimeError("No simulated world is connected to this deployment")
    rows = db.execute(select(Customer.customer_ref, Customer.city, Customer.region, Customer.plan, Customer.tenure_days, Customer.lifetime_value,
                             Customer.platform, Customer.os_version)).all()
    df = pd.DataFrame(rows, columns=["customer_id", "city", "region", "plan", "tenure_days", "lifetime_value", "platform", "os_version"]).fillna({"os_version": ""})
    return World(state, df)


def sync(db: Session, until: datetime | None = None, *, scenario_id: int | None = None, injected: bool = False, user_id: int | None = None) -> dict:
    """Regenerate everything visible at ``until`` and ingest it; unchanged rows are skipped, changed rows become new revisions."""
    until = until or get_sim_now(db)
    frames = load_world(db).export(until)
    reports = ingestion.ingest_world_frames(db, frames, user_id=user_id, scenario_id=scenario_id, is_injected=injected)
    set_sim_now(db, until)
    db.flush()
    return {k: {"inserted": v["inserted"], "revised": v["revised"], "unchanged": v["unchanged"]} for k, v in reports.items()}


def advance(db: Session, days: int, user_id: int | None = None) -> dict:
    new_now = get_sim_now(db) + timedelta(days=days)
    out = sync(db, new_now, user_id=user_id)
    from app.agents.context import Ctx

    persist_history(db, Ctx(db, "advance").view)
    return {"sim_now": new_now.isoformat(), "ingested": out}
