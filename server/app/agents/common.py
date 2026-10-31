from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models import Investigation


def get_investigation(db: Session, issue_id: int) -> Investigation:
    inv = db.scalar(select(Investigation).where(Investigation.issue_id == issue_id))
    if inv is None:
        inv = Investigation(issue_id=issue_id, status="queued", stage="created", iteration=1, state={})
        db.add(inv)
        db.flush()
    return inv


def inv_state(db: Session, issue_id: int) -> dict:
    return dict(get_investigation(db, issue_id).state or {})


def save_inv_state(db: Session, issue_id: int, key: str, value) -> None:
    inv = get_investigation(db, issue_id)
    state = dict(inv.state or {})
    state[key] = value
    inv.state = state
    flag_modified(inv, "state")
    db.flush()
