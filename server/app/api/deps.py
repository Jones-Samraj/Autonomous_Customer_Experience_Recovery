from __future__ import annotations

import logging
from typing import Callable

from app.core.security import ROLE_ANALYST, ROLE_APPROVER, require_roles
from app.db import SessionLocal, get_engine

log = logging.getLogger("cx.api")

analyst = require_roles(ROLE_ANALYST, ROLE_APPROVER)  # may run analyses, upload data, use the simulator
approver = require_roles(ROLE_APPROVER)  # may approve / reject / execute / roll back
admin = require_roles()  # admin only


def run_in_background(fn: Callable, *args, **kwargs) -> None:
    """Run a workflow in its own DB session (request sessions are closed when the response is sent)."""
    get_engine()
    db = SessionLocal()
    try:
        fn(db, *args, **kwargs)
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("background task %s failed", getattr(fn, "__name__", fn))
    finally:
        db.close()
