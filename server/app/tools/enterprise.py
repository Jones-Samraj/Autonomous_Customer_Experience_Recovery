"""Simulated enterprise systems (ITSM, notification gateway, finance ERP, operations control plane).

Tools are the ONLY way the platform changes anything. They accept structured, validated arguments built from an approved
intervention record - never free text from customers or an LLM. Each tool has a compensating action for rollback.
"""
from __future__ import annotations

import zlib
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db import utcnow
from app.models import CustomerNotification, DetectedIssue, Intervention, ServiceTicket
from app.sim import response


class TransientToolError(Exception):
    """Simulated 5xx / timeout - safe to retry."""


class PermanentToolError(Exception):
    """Simulated validation / authorisation failure - never retried."""


def maybe_fail(s: Settings, key: str, attempt: int) -> None:
    if s.tool_failure_rate >= 1.0:
        raise TransientToolError(f"503 Service Unavailable from simulated system (key={key})")
    if s.tool_failure_rate > 0 and attempt == 1 and (zlib.crc32(key.encode()) % 1000) / 1000 < s.tool_failure_rate:
        raise TransientToolError(f"503 Service Unavailable from simulated system (key={key})")


def _ticket_no(db: Session, prefix: str) -> str:
    n = (db.scalar(select(func.count()).select_from(ServiceTicket)) or 0) + 1
    return f"{prefix}-{n:05d}"


def create_service_ticket(db: Session, iv: Intervention, args: dict) -> dict:
    issue = db.get(DetectedIssue, iv.issue_id)
    kind = "support_priority" if iv.intervention_type == "prioritise_support_queue" else "incident"
    t = ServiceTicket(ticket_no=_ticket_no(db, "INC" if kind == "incident" else "SUP"), kind=kind, department=(iv.params or {}).get("department"),
                      title=f"[{issue.code}] {iv.title}", body=(iv.rationale or "")[:900], priority={"critical": "P1", "high": "P2"}.get(issue.severity, "P3"),
                      status="open", intervention_id=iv.id)
    db.add(t)
    db.flush()
    return {"ticket_no": t.ticket_no, "kind": kind, "priority": t.priority}


def assign_incident(db: Session, iv: Intervention, args: dict) -> dict:
    t = db.scalar(select(ServiceTicket).where(ServiceTicket.intervention_id == iv.id, ServiceTicket.kind.in_(["incident", "support_priority"])).order_by(ServiceTicket.id.desc()))
    if t is None:
        raise PermanentToolError("No ticket exists to assign")
    t.department, t.status = (iv.params or {}).get("department"), "assigned"
    db.flush()
    return {"ticket_no": t.ticket_no, "assigned_to": t.department}


def send_customer_notification(db: Session, iv: Intervention, args: dict) -> dict:
    issue = db.get(DetectedIssue, iv.issue_id)
    n = int((iv.params or {}).get("units") or 0)
    msg = (f"We are aware some customers are experiencing {issue.category.lower()}. Our team is working on a fix and we will update you shortly. "
           "We are sorry for the inconvenience.")
    row = CustomerNotification(intervention_id=iv.id, channel="push+email", audience={"issue": issue.code, "criteria": "customers with a linked failure since onset"},
                               recipients=n, message=msg, status="sent")
    db.add(row)
    db.flush()
    return {"notification_id": row.id, "recipients": n, "channel": row.channel}


def create_escalation_request(db: Session, iv: Intervention, args: dict) -> dict:
    issue = db.get(DetectedIssue, iv.issue_id)
    t = ServiceTicket(ticket_no=_ticket_no(db, "ESC"), kind="escalation", department=(iv.params or {}).get("department"),
                      title=f"[{issue.code}] Escalation: {issue.title}", body=issue.description, priority="P1" if issue.severity in ("critical", "high") else "P2",
                      status="open", intervention_id=iv.id)
    db.add(t)
    db.flush()
    return {"ticket_no": t.ticket_no, "escalated_to": t.department}


def create_refund_approval_request(db: Session, iv: Intervention, args: dict) -> dict:
    amount = float((iv.params or {}).get("amount_inr") or 0)
    t = ServiceTicket(ticket_no=_ticket_no(db, "RFD"), kind="refund_approval", department="Finance Operations",
                      title=f"Goodwill compensation request ({iv.code})", body=f"Requested amount INR {amount:,.0f} for severely affected customers.",
                      priority="P2", status="pending_finance", intervention_id=iv.id)
    db.add(t)
    db.flush()
    return {"ticket_no": t.ticket_no, "amount_inr": amount, "status": t.status}


def apply_operational_change(db: Session, iv: Intervention, args: dict) -> dict:
    change = (iv.params or {}).get("change")
    if not change:
        raise PermanentToolError("Intervention has no operational change to apply")
    return {"change": change, **response.apply_change(db, iv.code, iv.intervention_type, (iv.params or {}).get("aspect"))}


def _close(db: Session, iv: Intervention, kinds: list[str]) -> dict:
    n = 0
    for t in db.scalars(select(ServiceTicket).where(ServiceTicket.intervention_id == iv.id, ServiceTicket.kind.in_(kinds), ServiceTicket.status != "cancelled")):
        t.status, t.closed_at = "cancelled", utcnow()
        n += 1
    return {"tickets_cancelled": n}


def _recall(db: Session, iv: Intervention, args: dict) -> dict:
    n = 0
    for r in db.scalars(select(CustomerNotification).where(CustomerNotification.intervention_id == iv.id)):
        r.status = "recalled"
        n += 1
    return {"notifications_recalled": n}


def _revert(db: Session, iv: Intervention, args: dict) -> dict:
    return response.revert_change(db, iv.code)


TOOLS = {
    "create_service_ticket": (create_service_ticket, lambda db, iv, a: _close(db, iv, ["incident", "support_priority"]), "ITSM"),
    "assign_incident": (assign_incident, lambda db, iv, a: {"note": "assignment cleared with ticket"}, "ITSM"),
    "send_customer_notification": (send_customer_notification, _recall, "Notification Gateway"),
    "create_escalation_request": (create_escalation_request, lambda db, iv, a: _close(db, iv, ["escalation"]), "ITSM"),
    "create_refund_approval_request": (create_refund_approval_request, lambda db, iv, a: _close(db, iv, ["refund_approval"]), "Finance ERP"),
    "apply_operational_change": (apply_operational_change, _revert, "Operations Control Plane"),
}


def iso_now(dt: datetime) -> str:
    return dt.isoformat()
