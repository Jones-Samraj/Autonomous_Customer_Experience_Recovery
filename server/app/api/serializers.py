from __future__ import annotations

from datetime import datetime

from app.models import (ApprovalRequest, CustomerSignal, DetectedIssue, ExecutionLog, Intervention, RootCauseHypothesis, ServiceTicket)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def issue_out(i: DetectedIssue, full: bool = False) -> dict:
    d = {"id": i.id, "code": i.code, "title": i.title, "description": i.description, "category": i.category, "aspect": i.aspect, "status": i.status, "severity": i.severity,
         "severity_score": i.severity_score, "detection_confidence": i.detection_confidence, "support_count": i.support_count, "duplicate_count": i.duplicate_count,
         "growth_rate": i.growth_rate, "kpi_name": i.kpi_name, "baseline_rate": i.baseline_rate, "current_rate": i.current_rate, "first_detected_at": iso(i.first_detected_at),
         "onset_at": iso(i.onset_at), "iteration": i.iteration, "reopen_count": i.reopen_count, "updated_at": iso(i.updated_at)}
    if full:
        d["severity_breakdown"] = i.severity_breakdown
        d["stats"] = i.stats
    else:
        d["evidence_references"] = i.support_count
    return d


def evidence_out(e) -> dict:
    return {"id": e.id, "relation": e.relation, "kind": e.kind, "summary": e.summary, "weight": e.weight, "payload": e.payload, "signal_id": e.signal_id, "event_id": e.event_id,
            "release_id": e.release_id}


def hypothesis_out(h: RootCauseHypothesis, evidence: bool = True) -> dict:
    d = {"id": h.id, "issue_id": h.issue_id, "iteration": h.iteration, "is_current": h.is_current, "rank": h.rank, "title": h.title, "cause_type": h.cause_type,
         "statement": h.statement, "narrative": h.narrative, "confidence": h.confidence, "evidence_quality": h.evidence_quality, "quality_label": h.quality_label, "status": h.status,
         "causal_claim": h.causal_claim, "alternatives": h.alternatives, "additional_data_needed": h.additional_data_needed, "scope": h.scope,
         "features": {k: v for k, v in (h.features or {}).items() if k in ("coverage", "attribution", "residual", "violation", "has_control", "exposed_n", "rate_exposed", "rate_unexposed",
                                                                          "p0_exposed", "adj_vs", "adj_rd", "kpi", "score")}}
    if evidence:
        ev = [evidence_out(e) for e in h.evidence]
        d["supporting_evidence"] = sorted([e for e in ev if e["relation"] == "supports"], key=lambda e: -e["weight"])
        d["contradicting_evidence"] = sorted([e for e in ev if e["relation"] == "contradicts"], key=lambda e: -e["weight"])
        d["context_evidence"] = [e for e in ev if e["relation"] == "context"]
    return d


def intervention_out(i: Intervention) -> dict:
    return {"id": i.id, "code": i.code, "issue_id": i.issue_id, "iteration": i.iteration, "type": i.intervention_type, "title": i.title, "description": i.description,
            "role": i.role, "status": i.status, "verification_status": i.verification_status, "requires_approval": i.requires_approval, "is_consequential": i.is_consequential,
            "expected_impact": i.expected_impact, "cost_inr": i.cost_inr, "execution_hours": i.execution_hours, "customer_benefit": i.customer_benefit,
            "business_risk": i.business_risk, "feasibility": i.feasibility, "confidence": i.confidence, "reversibility": i.reversibility, "utility": i.utility, "rank": i.rank,
            "is_recommended": i.is_recommended, "rationale": i.rationale, "target_hypothesis_id": i.target_hypothesis_id, "params": i.params, "superseded": i.superseded,
            "created_at": iso(i.created_at), "approved_at": iso(i.approved_at), "executed_at": iso(i.executed_at), "verified_at": iso(i.verified_at),
            "rolled_back_at": iso(i.rolled_back_at)}


def approval_out(a: ApprovalRequest, issue: DetectedIssue | None = None, hypothesis: RootCauseHypothesis | None = None) -> dict:
    iv = a.intervention
    d = {"id": a.id, "status": a.status, "requested_at": iso(a.requested_at), "decided_by": a.decided_by, "decided_at": iso(a.decided_at), "comment": a.comment, "summary": a.summary,
         "intervention": intervention_out(iv)}
    if issue:
        d["issue"] = {"id": issue.id, "code": issue.code, "title": issue.title, "severity": issue.severity, "category": issue.category}
    if hypothesis:
        d["target_hypothesis"] = hypothesis_out(hypothesis)
    return d


def signal_out(s: CustomerSignal, full: bool = False) -> dict:
    d = {"id": s.id, "external_id": s.external_id, "source_type": s.source_type, "source_id": s.source_id, "customer_id": s.customer_id, "occurred_at": iso(s.occurred_at),
         "text": s.text, "numeric_value": s.numeric_value, "metric_name": s.metric_name, "product": s.product, "segment": s.segment, "region": s.region,
         "reliability": s.reliability, "sentiment": s.sentiment, "primary_aspect": s.primary_aspect, "is_flagged": s.is_flagged, "flag_reason": s.flag_reason,
         "is_injected": s.is_injected, "revision": s.revision}
    if full:
        d["attributes"], d["aspects"] = s.attributes, s.aspects
    return d


def log_out(l: ExecutionLog) -> dict:
    return {"id": l.id, "intervention_id": l.intervention_id, "action": l.action, "system": l.simulated_system, "idempotency_key": l.idempotency_key, "attempt": l.attempt,
            "status": l.status, "request": l.request, "response": l.response, "error": l.error, "duration_ms": l.duration_ms, "created_at": iso(l.created_at)}


def ticket_out(t: ServiceTicket) -> dict:
    return {"id": t.id, "ticket_no": t.ticket_no, "kind": t.kind, "department": t.department, "title": t.title, "body": t.body, "priority": t.priority, "status": t.status,
            "intervention_id": t.intervention_id, "created_at": iso(t.created_at), "closed_at": iso(t.closed_at)}
