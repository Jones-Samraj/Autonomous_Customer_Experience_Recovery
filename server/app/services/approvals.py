"""Human approval workflow for consequential interventions."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import ApprovalRequest, DetectedIssue, Intervention, RootCauseHypothesis, User
from app.services.system import audit, notify


class WorkflowError(Exception):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def submit(db: Session, intervention_id: int, user: User) -> ApprovalRequest:
    iv = db.get(Intervention, intervention_id)
    if iv is None:
        raise WorkflowError("Intervention not found", 404)
    if iv.status != "proposed" or iv.superseded:
        raise WorkflowError(f"Only proposed interventions can be submitted (status is '{iv.status}')")
    target = db.get(RootCauseHypothesis, iv.target_hypothesis_id) if iv.target_hypothesis_id else None
    summary = {"cost_inr": iv.cost_inr, "expected_impact": iv.expected_impact, "business_risk": iv.business_risk, "reversibility": iv.reversibility,
               "target_hypothesis": target.title if target else None, "target_confidence": target.confidence if target else None,
               "evidence_quality": target.quality_label if target else None, "iteration": iv.iteration, "submitted_by": user.email}
    iv.status = "pending_approval" if iv.requires_approval else "approved"
    if not iv.requires_approval:
        iv.approved_at = utcnow()
    ar = ApprovalRequest(intervention_id=iv.id, status="pending" if iv.requires_approval else "approved", summary=summary, decided_at=None if iv.requires_approval else utcnow(),
                         comment=None if iv.requires_approval else "Auto-approved by policy: non-consequential action")
    db.add(ar)
    audit(db, user.id, "approval.submit", "intervention", iv.id, summary)
    notify(db, f"Approval requested: {iv.code}", iv.title, "warning", "/approvals")
    db.flush()
    return ar


def decide(db: Session, approval_id: int, approve: bool, user: User, comment: str | None = None) -> ApprovalRequest:
    ar = db.get(ApprovalRequest, approval_id)
    if ar is None:
        raise WorkflowError("Approval request not found", 404)
    if ar.status != "pending":
        raise WorkflowError(f"Approval request is already '{ar.status}'")
    iv = ar.intervention
    if iv.superseded:
        raise WorkflowError("This intervention was superseded by a newer investigation iteration")
    ar.status = "approved" if approve else "rejected"
    ar.decided_by, ar.decided_at, ar.comment = user.id, utcnow(), comment
    iv.status = "approved" if approve else "rejected"
    if approve:
        iv.approved_at = utcnow()
    issue = db.get(DetectedIssue, iv.issue_id)
    audit(db, user.id, "approval.approve" if approve else "approval.reject", "intervention", iv.id, {"comment": comment, "issue": issue.code})
    notify(db, f"Intervention {'approved' if approve else 'rejected'}: {iv.code}", f"{iv.title} - by {user.full_name}", "success" if approve else "info", "/approvals")
    if not approve and not db.scalar(select(ApprovalRequest.id).join(Intervention, Intervention.id == ApprovalRequest.intervention_id).where(
            Intervention.issue_id == iv.issue_id, ApprovalRequest.status == "pending", Intervention.superseded.is_(False)).limit(1)):
        issue.status = "investigating" if issue.status == "awaiting_approval" else issue.status
    db.flush()
    return ar
