"""System settings helpers: simulated clock, world state, audit trail and notifications."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import AuditLog, Notification, SystemSetting


def get_setting(db: Session, key: str, default=None):
    row = db.get(SystemSetting, key)
    return row.value if row is not None else default


def set_setting(db: Session, key: str, value) -> None:
    row = db.get(SystemSetting, key)
    if row is None:
        db.add(SystemSetting(key=key, value=value))
    else:
        row.value = value
        row.updated_at = utcnow()
    db.flush()


def get_sim_now(db: Session) -> datetime:
    v = get_setting(db, "sim_now")
    return datetime.fromisoformat(v) if v else datetime(utcnow().year, utcnow().month, utcnow().day)


def set_sim_now(db: Session, dt: datetime) -> None:
    set_setting(db, "sim_now", dt.strftime("%Y-%m-%dT%H:%M:%S"))


def audit(db: Session, user_id: int | None, action: str, entity_type: str | None = None, entity_id=None,
          detail: dict | None = None, ip: str | None = None) -> None:
    db.add(AuditLog(user_id=user_id, action=action, entity_type=entity_type,
                    entity_id=str(entity_id) if entity_id is not None else None, detail=detail or {}, ip_address=ip))


def notify(db: Session, title: str, body: str = "", level: str = "info", link: str | None = None) -> None:
    db.add(Notification(title=title[:200], body=body, level=level, link=link))
    from app.core.events import publish

    publish({"type": "notification", "level": level, "title": title, "body": body, "link": link})
