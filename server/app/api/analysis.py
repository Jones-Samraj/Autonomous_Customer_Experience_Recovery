from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents import (impact_agent, intervention_agent, orchestrator, rootcause_agent, segment_agent)
from app.agents.common import get_investigation, inv_state
from app.agents.context import Ctx
from app.api.deps import analyst, approver, run_in_background
from app.api.serializers import (approval_out, hypothesis_out, intervention_out, issue_out, iso, log_out, ticket_out)
from app.core.security import get_current_user
from app.db import get_db
from app.models import (AgentExecutionHistory, ApprovalRequest, BusinessImpactEstimate, CustomerNotification, DetectedIssue, ExecutionLog, Intervention,
                        InterventionComparison, Investigation, IssueCluster, IssueEvidence, CustomerSignal, RootCauseHypothesis, Scenario, ServiceTicket, User)
from app.schemas import DecisionIn
from app.services import approvals as approval_svc
from app.services import graph as graph_svc
from app.services import pipeline
from app.services.approvals import WorkflowError
from app.services.system import audit
from app.agents import execution_agent

router = APIRouter(tags=["Issues & Investigation"])


def _issue(db: Session, issue_id: int) -> DetectedIssue:
    i = db.get(DetectedIssue, issue_id)
    if i is None:
        raise HTTPException(404, "Issue not found")
    return i


@router.post("/issues/detect", summary="Run signal profiling and emerging-issue detection")
def detect(db: Session = Depends(get_db), user=Depends(analyst)):
    try:
        return pipeline.run_detection(db, user.id)
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))


@router.post("/pipeline/run", status_code=202, summary="Run detection and investigate every issue in the background")
def run_pipeline(tasks: BackgroundTasks, user=Depends(analyst)):
    tasks.add_task(run_in_background, pipeline.run_full_analysis, user.id)
    return {"status": "started", "message": "Analysis is running; follow progress over the WebSocket or the agent history."}


@router.get("/issues", summary="Detected issues")
def list_issues(status: str | None = None, severity: str | None = None, db: Session = Depends(get_db), _=Depends(get_current_user)):
    q = select(DetectedIssue).order_by(DetectedIssue.severity_score.desc())
    if status:
        q = q.where(DetectedIssue.status == status)
    if severity:
        q = q.where(DetectedIssue.severity == severity)
    out = []
    for i in db.scalars(q):
        d = issue_out(i)
        top = db.scalar(select(RootCauseHypothesis).where(RootCauseHypothesis.issue_id == i.id, RootCauseHypothesis.is_current.is_(True), RootCauseHypothesis.rank == 1))
        d["top_hypothesis"] = {"title": top.title, "confidence": top.confidence, "status": top.status} if top else None
        d["pending_approvals"] = db.scalar(select(func.count()).select_from(ApprovalRequest).join(Intervention, Intervention.id == ApprovalRequest.intervention_id)
                                           .where(Intervention.issue_id == i.id, ApprovalRequest.status == "pending")) or 0
        d["clusters"] = db.scalar(select(func.count()).select_from(IssueCluster).where(IssueCluster.issue_id == i.id)) or 0
        d["sparkline"] = [v for _, v in sorted(((i.stats or {}).get("daily_counts") or {}).items())]
        out.append(d)
    return out


@router.get("/clusters", summary="Semantic complaint clusters")
def clusters(issue_id: int | None = None, db: Session = Depends(get_db), _=Depends(get_current_user)):
    q = select(IssueCluster).order_by(IssueCluster.size.desc())
    if issue_id:
        q = q.where(IssueCluster.issue_id == issue_id)
    return [{"id": c.id, "issue_id": c.issue_id, "label": c.label, "aspect": c.aspect, "terms": c.top_terms, "size": c.size, "baseline_mean": c.baseline_mean,
             "recent_count": c.recent_count, "expected": c.expected_count, "z": c.z_score, "growth": c.growth_rate, "is_new": c.is_new, "is_anomalous": c.is_anomalous,
             "persistence_days": c.persistence_days, "daily_counts": c.daily_counts} for c in db.scalars(q)]


def _kpi_series(db: Session, issue: DetectedIssue) -> list[dict]:
    if not issue.kpi_name:
        return []
    d = Ctx(db, "api", issue.id).view.daily_rate(issue.kpi_name)
    return [{"date": r.date.strftime("%Y-%m-%d"), "n": int(r.n), "k": int(r.k), "rate": float(r.rate)} for r in d.itertuples()]


@router.get("/issues/{issue_id}", summary="Issue detail with clusters, KPI series and business timeline")
def issue_detail(issue_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    i = _issue(db, issue_id)
    d = issue_out(i, full=True)
    d["clusters"] = [{"id": c.id, "label": c.label, "terms": c.top_terms, "size": c.size, "z": c.z_score, "growth": c.growth_rate, "is_new": c.is_new, "is_anomalous": c.is_anomalous,
                      "recent_count": c.recent_count, "expected": c.expected_count, "persistence_days": c.persistence_days}
                     for c in db.scalars(select(IssueCluster).where(IssueCluster.issue_id == issue_id).order_by(IssueCluster.size.desc()))]
    d["kpi_series"] = _kpi_series(db, i)
    biz = []
    if i.onset_at:
        biz.append({"at": iso(i.onset_at), "kind": "onset", "title": "Anomaly onset", "detail": "Change-point detected in the issue KPI"})
    if i.first_detected_at:
        biz.append({"at": iso(i.first_detected_at), "kind": "detected", "title": "Issue first detectable", "detail": "Cumulative evidence crossed the detection threshold"})
    for iv in db.scalars(select(Intervention).where(Intervention.issue_id == issue_id, Intervention.executed_at.is_not(None))):
        biz.append({"at": iso(iv.executed_at), "kind": "executed", "title": f"Executed: {iv.title}", "detail": f"{iv.code}, verification: {iv.verification_status}"})
    d["business_timeline"] = sorted(biz, key=lambda x: x["at"])
    d["evidence_count"] = db.scalar(select(func.count()).select_from(IssueEvidence).where(IssueEvidence.issue_id == issue_id)) or 0
    return d


@router.get("/issues/{issue_id}/evidence", summary="Evidence records linked to an issue")
def issue_evidence(issue_id: int, page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), _=Depends(get_current_user)):
    from app.api.serializers import signal_out

    base = select(IssueEvidence, CustomerSignal).join(CustomerSignal, CustomerSignal.id == IssueEvidence.signal_id).where(IssueEvidence.issue_id == issue_id)
    total = db.scalar(select(func.count()).select_from(IssueEvidence).where(IssueEvidence.issue_id == issue_id)) or 0
    rows = db.execute(base.order_by(CustomerSignal.occurred_at.desc()).offset((page - 1) * size).limit(size)).all()
    return {"total": total, "items": [{**signal_out(s), "relevance": e.relevance, "is_duplicate": e.is_duplicate, "cluster_id": e.cluster_id} for e, s in rows]}


@router.get("/investigations", summary="All investigations")
def list_investigations(db: Session = Depends(get_db), _=Depends(get_current_user)):
    out = []
    for inv in db.scalars(select(Investigation)):
        i = db.get(DetectedIssue, inv.issue_id)
        out.append({"id": inv.id, "issue": issue_out(i), "status": inv.status, "stage": inv.stage, "iteration": inv.iteration, "updated_at": iso(inv.updated_at)})
    return out


@router.get("/investigations/{issue_id}", summary="Full investigation: hypotheses, evidence, segments, impact, interventions and history")
def investigation(issue_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    i = _issue(db, issue_id)
    inv = get_investigation(db, issue_id)
    hyps = list(db.scalars(select(RootCauseHypothesis).where(RootCauseHypothesis.issue_id == issue_id).order_by(RootCauseHypothesis.iteration.desc(), RootCauseHypothesis.rank)))
    current = [hypothesis_out(h) for h in hyps if h.is_current]
    past = {}
    for h in hyps:
        if not h.is_current:
            past.setdefault(h.iteration, []).append({"id": h.id, "title": h.title, "cause_type": h.cause_type, "confidence": h.confidence, "status": h.status, "rank": h.rank})
    impact = [{"metric": e.metric, "label": e.label, "value": e.value, "unit": e.unit, "kind": e.kind, "formula": e.formula, "inputs": e.inputs, "assumptions": e.assumptions,
               "ci_low": e.ci_low, "ci_high": e.ci_high, "calculated_at": iso(e.calculated_at), "iteration": e.iteration}
              for e in db.scalars(select(BusinessImpactEstimate).where(BusinessImpactEstimate.issue_id == issue_id, BusinessImpactEstimate.is_current.is_(True)))]
    ivs = [intervention_out(x) for x in db.scalars(select(Intervention).where(Intervention.issue_id == issue_id).order_by(Intervention.iteration.desc(), Intervention.role, Intervention.rank))]
    history = [{"id": h.id, "run_id": h.run_id, "agent": h.agent, "task": h.task, "input_summary": h.input_summary, "reasoning_summary": h.reasoning_summary, "output_summary": h.output_summary,
                "status": h.status, "attempt": h.attempt, "started_at": iso(h.started_at), "duration_ms": h.duration_ms, "error": h.error, "llm_cost_usd": h.llm_cost_usd}
               for h in db.scalars(select(AgentExecutionHistory).where(AgentExecutionHistory.issue_id == issue_id).order_by(AgentExecutionHistory.id.desc()).limit(150))]
    timeline = []
    for h in reversed(history):
        timeline.append({"at": h["started_at"], "kind": "agent", "title": h["agent"], "detail": h["reasoning_summary"], "status": h["status"], "run_id": h["run_id"]})
    for a in db.scalars(select(ApprovalRequest).join(Intervention, Intervention.id == ApprovalRequest.intervention_id).where(Intervention.issue_id == issue_id)):
        timeline.append({"at": iso(a.requested_at), "kind": "approval", "title": f"Approval requested: {a.intervention.code}", "detail": a.intervention.title, "status": "pending"})
        if a.decided_at and a.decided_by:
            timeline.append({"at": iso(a.decided_at), "kind": "approval", "title": f"Approval {a.status}: {a.intervention.code}", "detail": a.comment or "", "status": a.status})
    for s in db.scalars(select(Scenario).where(Scenario.issue_id == issue_id)):
        timeline.append({"at": iso(s.created_at), "kind": "scenario", "title": f"Dynamic scenario: {s.name}", "detail": (s.diff or {}).get("narrative", "")[:300], "status": s.status})
    timeline.sort(key=lambda x: x["at"] or "")
    return {"issue": issue_out(i, full=True), "status": inv.status, "stage": inv.stage, "iteration": i.iteration, "hypotheses": current, "previous_hypotheses": past,
            "segmentation": inv_state(db, issue_id).get("segmentation"), "impact": impact, "interventions": ivs, "history": history[:60], "timeline": timeline,
            "approvals": [approval_out(a) for a in db.scalars(select(ApprovalRequest).join(Intervention, Intervention.id == ApprovalRequest.intervention_id)
                                                              .where(Intervention.issue_id == issue_id).order_by(ApprovalRequest.id.desc()))]}


@router.post("/investigations/{issue_id}/run", summary="(Re-)run the multi-agent investigation for an issue")
def run_investigation(issue_id: int, background: bool = False, tasks: BackgroundTasks = None, db: Session = Depends(get_db), user=Depends(analyst)):
    i = _issue(db, issue_id)
    trig = "new_evidence" if i.status in ("open", "investigating", "awaiting_approval", "reopened", "monitoring", "resolved") and get_investigation(db, issue_id).status not in ("queued",) else "investigate"
    if background and tasks is not None:
        tasks.add_task(run_in_background, pipeline.investigate, issue_id, trig, user.id)
        return {"status": "started"}
    return pipeline.investigate(db, issue_id, trig, user.id)


@router.get("/investigations/{issue_id}/graph", summary="Evidence graph linking signals, issue, segments, events, hypotheses and interventions")
def evidence_graph(issue_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    _issue(db, issue_id)
    return graph_svc.build(db, issue_id)


@router.get("/history", summary="Agent execution history (decisions and reasoning summaries)")
def agent_history(issue_id: int | None = None, run_id: str | None = None, agent: str | None = None, page: int = Query(1, ge=1), size: int = Query(40, ge=1, le=200),
                  db: Session = Depends(get_db), _=Depends(get_current_user)):
    q = select(AgentExecutionHistory)
    cnt = select(func.count()).select_from(AgentExecutionHistory)
    for col, val in ((AgentExecutionHistory.issue_id, issue_id), (AgentExecutionHistory.run_id, run_id), (AgentExecutionHistory.agent, agent)):
        if val is not None:
            q, cnt = q.where(col == val), cnt.where(col == val)
    rows = db.scalars(q.order_by(AgentExecutionHistory.id.desc()).offset((page - 1) * size).limit(size))
    codes = {i.id: i.code for i in db.scalars(select(DetectedIssue))}
    return {"total": db.scalar(cnt) or 0, "items": [{"id": h.id, "run_id": h.run_id, "issue_id": h.issue_id, "issue_code": codes.get(h.issue_id), "agent": h.agent, "task": h.task,
                                                      "input_summary": h.input_summary, "reasoning_summary": h.reasoning_summary, "output_summary": h.output_summary, "status": h.status,
                                                      "attempt": h.attempt, "started_at": iso(h.started_at), "duration_ms": h.duration_ms, "error": h.error,
                                                      "llm_tokens": (h.llm_tokens_in or 0) + (h.llm_tokens_out or 0), "llm_cost_usd": h.llm_cost_usd} for h in rows]}


def _single(db: Session, issue_id: int, name: str, fn):
    _issue(db, issue_id)
    ctx = Ctx(db, orchestrator.new_run_id(), issue_id)
    res, err = orchestrator.record(ctx, orchestrator.LABEL[name][0], orchestrator.LABEL[name][1], issue_id, lambda: fn(ctx, issue_id))
    if err:
        raise HTTPException(500, f"{orchestrator.LABEL[name][0]} failed: {err}")
    return {"run_id": ctx.run_id, "reasoning": res.reasoning, "output": res.output}


@router.post("/issues/{issue_id}/segmentation", summary="Run the Customer Segmentation agent")
def run_segmentation(issue_id: int, db: Session = Depends(get_db), _=Depends(analyst)):
    return _single(db, issue_id, "segmentation", segment_agent.run)


@router.get("/issues/{issue_id}/segmentation", summary="Segmentation result (affected segments, geography, products)")
def get_segmentation(issue_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    _issue(db, issue_id)
    return inv_state(db, issue_id).get("segmentation") or {}


@router.post("/issues/{issue_id}/root-cause", summary="Run the Root Cause Investigation agent")
def run_root_cause(issue_id: int, db: Session = Depends(get_db), _=Depends(analyst)):
    return _single(db, issue_id, "root_cause", rootcause_agent.run)


@router.post("/issues/{issue_id}/impact", summary="Run the Business Impact agent")
def run_impact(issue_id: int, db: Session = Depends(get_db), _=Depends(analyst)):
    return _single(db, issue_id, "impact", impact_agent.run)


@router.get("/issues/{issue_id}/impact", summary="Impact estimates with formulas, inputs, assumptions and ranges")
def get_impact(issue_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    _issue(db, issue_id)
    return [{"metric": e.metric, "label": e.label, "value": e.value, "unit": e.unit, "kind": e.kind, "formula": e.formula, "inputs": e.inputs, "assumptions": e.assumptions,
             "ci_low": e.ci_low, "ci_high": e.ci_high, "calculated_at": iso(e.calculated_at)}
            for e in db.scalars(select(BusinessImpactEstimate).where(BusinessImpactEstimate.issue_id == issue_id, BusinessImpactEstimate.is_current.is_(True)))]


@router.post("/issues/{issue_id}/interventions/plan", summary="Run the Intervention Planning agent")
def plan_interventions(issue_id: int, db: Session = Depends(get_db), _=Depends(analyst)):
    return _single(db, issue_id, "intervention_planning", intervention_agent.run)


@router.get("/interventions", summary="Interventions with comparison data")
def list_interventions(issue_id: int | None = None, status: str | None = None, role: str | None = None, current: bool = True, db: Session = Depends(get_db), _=Depends(get_current_user)):
    q = select(Intervention).order_by(Intervention.issue_id, Intervention.iteration.desc(), Intervention.role, Intervention.rank)
    if issue_id:
        q = q.where(Intervention.issue_id == issue_id)
    if status:
        q = q.where(Intervention.status == status)
    if role:
        q = q.where(Intervention.role == role)
    if current:
        q = q.where(Intervention.superseded.is_(False))
    comps = {c.intervention_id: c for c in db.scalars(select(InterventionComparison))}
    codes = {i.id: i for i in db.scalars(select(DetectedIssue))}
    out = []
    for iv in db.scalars(q):
        d = intervention_out(iv)
        c = comps.get(iv.id)
        d["criteria"] = c.criteria if c else None
        d["issue"] = {"id": iv.issue_id, "code": codes[iv.issue_id].code, "title": codes[iv.issue_id].title, "iteration": codes[iv.issue_id].iteration}
        out.append(d)
    return out


@router.get("/interventions/{intervention_id}", summary="Intervention detail incl. execution logs and enterprise records")
def intervention_detail(intervention_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    iv = db.get(Intervention, intervention_id)
    if iv is None:
        raise HTTPException(404, "Intervention not found")
    comp = db.scalar(select(InterventionComparison).where(InterventionComparison.intervention_id == iv.id))
    tgt = db.get(RootCauseHypothesis, iv.target_hypothesis_id) if iv.target_hypothesis_id else None
    return {**intervention_out(iv), "criteria": comp.criteria if comp else None, "target_hypothesis": hypothesis_out(tgt) if tgt else None,
            "execution_logs": [log_out(x) for x in db.scalars(select(ExecutionLog).where(ExecutionLog.intervention_id == iv.id).order_by(ExecutionLog.id))],
            "tickets": [ticket_out(t) for t in db.scalars(select(ServiceTicket).where(ServiceTicket.intervention_id == iv.id))],
            "approvals": [approval_out(a) for a in db.scalars(select(ApprovalRequest).where(ApprovalRequest.intervention_id == iv.id))]}


@router.post("/interventions/{intervention_id}/submit", summary="Submit a proposed intervention for human approval")
def submit_intervention(intervention_id: int, db: Session = Depends(get_db), user: User = Depends(analyst)):
    try:
        ar = approval_svc.submit(db, intervention_id, user)
    except WorkflowError as exc:
        raise HTTPException(exc.status, str(exc))
    iv = ar.intervention
    issue = db.get(DetectedIssue, iv.issue_id)
    if issue.status in ("open", "investigating") and ar.status == "pending":
        issue.status = "awaiting_approval"
    db.commit()
    return approval_out(ar)


@router.post("/interventions/{intervention_id}/execute", summary="Execute an approved intervention (retry after failure)")
def execute_intervention(intervention_id: int, db: Session = Depends(get_db), user: User = Depends(approver)):
    iv = db.get(Intervention, intervention_id)
    if iv is None:
        raise HTTPException(404, "Intervention not found")
    if iv.status not in ("approved", "failed"):
        raise HTTPException(409, f"Intervention is '{iv.status}'; only approved interventions can be executed")
    return pipeline.execute_approved(db, intervention_id, user.id)


@router.post("/interventions/{intervention_id}/rollback", summary="Roll back an executed intervention")
def rollback_intervention(intervention_id: int, db: Session = Depends(get_db), user: User = Depends(approver)):
    iv = db.get(Intervention, intervention_id)
    if iv is None:
        raise HTTPException(404, "Intervention not found")
    ctx = Ctx(db, orchestrator.new_run_id(), iv.issue_id)
    try:
        res, err = orchestrator.record(ctx, "Recovery Execution Agent", f"Roll back {iv.code}", iv.issue_id, lambda: execution_agent.rollback(ctx, intervention_id, user.id))
    except PermissionError as exc:
        raise HTTPException(409, str(exc))
    if err:
        raise HTTPException(409 if isinstance(err, PermissionError) else 500, str(err))
    db.commit()
    return res.output


@router.get("/approvals", summary="Approval requests (pending and history)")
def list_approvals(status: str | None = None, db: Session = Depends(get_db), _=Depends(get_current_user)):
    q = select(ApprovalRequest).join(Intervention, Intervention.id == ApprovalRequest.intervention_id).where(Intervention.superseded.is_(False) | (ApprovalRequest.status != "pending"))
    if status:
        q = q.where(ApprovalRequest.status == status)
    out = []
    for a in db.scalars(q.order_by(ApprovalRequest.id.desc())):
        issue = db.get(DetectedIssue, a.intervention.issue_id)
        hyp = db.get(RootCauseHypothesis, a.intervention.target_hypothesis_id) if a.intervention.target_hypothesis_id else None
        d = approval_out(a, issue, hyp)
        d["decided_by_name"] = db.get(User, a.decided_by).full_name if a.decided_by else None
        out.append(d)
    return out


def _decide(db: Session, tasks: BackgroundTasks, approval_id: int, approve: bool, body: DecisionIn, user: User):
    try:
        ar = approval_svc.decide(db, approval_id, approve, user, body.comment)
    except WorkflowError as exc:
        raise HTTPException(exc.status, str(exc))
    db.commit()
    if approve:
        tasks.add_task(run_in_background, pipeline.execute_approved, ar.intervention_id, user.id)
    issue = db.get(DetectedIssue, ar.intervention.issue_id)
    d = approval_out(ar, issue)
    d["execution"] = "queued" if approve else None
    return d


@router.post("/approvals/{approval_id}/approve", summary="Approve an intervention (execution starts automatically)")
def approve(approval_id: int, body: DecisionIn, tasks: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(approver)):
    return _decide(db, tasks, approval_id, True, body, user)


@router.post("/approvals/{approval_id}/reject", summary="Reject an intervention")
def reject(approval_id: int, body: DecisionIn, tasks: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(approver)):
    return _decide(db, tasks, approval_id, False, body, user)


@router.get("/enterprise/tickets", summary="Simulated ITSM tickets created by the Execution agent")
def tickets(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return [ticket_out(t) for t in db.scalars(select(ServiceTicket).order_by(ServiceTicket.id.desc()).limit(200))]


@router.get("/enterprise/notifications", summary="Simulated customer-notification outbox")
def notif_outbox(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return [{"id": n.id, "intervention_id": n.intervention_id, "channel": n.channel, "recipients": n.recipients, "message": n.message, "status": n.status, "created_at": iso(n.created_at)}
            for n in db.scalars(select(CustomerNotification).order_by(CustomerNotification.id.desc()).limit(100))]


@router.get("/execution-logs", summary="Tool execution logs (retries, idempotency, failures)")
def execution_logs(intervention_id: int | None = None, db: Session = Depends(get_db), _=Depends(get_current_user)):
    q = select(ExecutionLog).order_by(ExecutionLog.id.desc()).limit(300)
    if intervention_id:
        q = select(ExecutionLog).where(ExecutionLog.intervention_id == intervention_id).order_by(ExecutionLog.id)
    return [log_out(x) for x in db.scalars(q)]
