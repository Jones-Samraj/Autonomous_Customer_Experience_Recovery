from __future__ import annotations

import importlib.util
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.agents.context import Ctx
from app.api.deps import admin, analyst, approver, run_in_background
from app.api.serializers import intervention_out, issue_out, iso
from app.core.config import get_settings
from app.core.security import get_current_user
from app.db import Base, get_db, get_engine
from app.models import (AgentExecutionHistory, ApprovalRequest, AuditLog, BusinessImpactEstimate, CustomerSignal, DetectedIssue, HypothesisEvidence, Intervention,
                        IssueEvidence, Notification, RecoveryKpi, RecoveryMeasurement, RootCauseHypothesis, Scenario, User)
from app.schemas import AdvanceIn, RetentionIn, ScenarioIn
from app.services import evaluation, pipeline, scenarios, seed, world_sync
from app.services.system import audit, get_sim_now

router = APIRouter(tags=["Monitoring, Simulator, Evaluation & System"])


# ----------------------------------------------------------------------------- dashboard
def _verification_results(db: Session) -> dict[int, dict]:
    latest: dict[int, dict] = {}
    for h in db.scalars(select(AgentExecutionHistory).where(AgentExecutionHistory.agent == "Verification & Learning Agent", AgentExecutionHistory.status == "succeeded")
                        .order_by(AgentExecutionHistory.id)):
        for r in (h.output_summary or {}).get("results", []):
            latest[r["intervention_id"]] = r
    return latest


def _kpi_series(db: Session, codes: list[str] | None = None) -> list[dict]:
    q = select(RecoveryKpi)
    if codes:
        q = q.where(RecoveryKpi.code.in_(codes))
    out = []
    for k in db.scalars(q):
        rows = db.execute(select(RecoveryMeasurement.measured_on, RecoveryMeasurement.value).where(RecoveryMeasurement.kpi_id == k.id, RecoveryMeasurement.issue_id.is_(None),
                                                                                                    RecoveryMeasurement.intervention_id.is_(None)).order_by(RecoveryMeasurement.measured_on)).all()
        series = [{"date": d.isoformat(), "value": v} for d, v in rows]
        base = [r["value"] for r in series[:14]]
        out.append({"code": k.code, "name": k.name, "unit": k.unit, "direction": k.direction, "target": k.target, "series": series,
                    "latest": series[-1]["value"] if series else None, "baseline": (sum(base) / len(base)) if base else None})
    return out


@router.get("/dashboard/overview", summary="Executive overview")
def overview(db: Session = Depends(get_db), _=Depends(get_current_user)):
    issues = list(db.scalars(select(DetectedIssue).where(DetectedIssue.status != "superseded")))
    confirmed = [i for i in issues if i.status != "watchlist"]
    est = {}
    for e in db.scalars(select(BusinessImpactEstimate).where(BusinessImpactEstimate.is_current.is_(True), BusinessImpactEstimate.metric.in_(["revenue_at_risk", "affected_customers_measured",
                                                                                                                                            "business_severity_score"]))):
        est.setdefault(e.issue_id, {})[e.metric] = e.value
    active = [i for i in confirmed if i.status != "resolved"]
    ver = _verification_results(db)
    decided = [r for r in ver.values() if r["verdict"] in ("recovered", "not_recovered")]
    pending = db.scalar(select(func.count()).select_from(ApprovalRequest).join(Intervention, Intervention.id == ApprovalRequest.intervention_id)
                        .where(ApprovalRequest.status == "pending", Intervention.superseded.is_(False))) or 0
    sev = {s: sum(1 for i in confirmed if i.severity == s) for s in ("critical", "high", "medium", "low")}
    recent = sorted(confirmed, key=lambda i: i.updated_at or i.created_at, reverse=True)[:6]
    return {
        "sim_now": get_sim_now(db).isoformat(),
        "kpis": {"total_issues": len(confirmed), "critical_issues": sev["critical"], "watchlist": len(issues) - len(confirmed),
                 "affected_customers": sum(est.get(i.id, {}).get("affected_customers_measured", 0) or 0 for i in active),
                 "revenue_at_risk": sum(est.get(i.id, {}).get("revenue_at_risk", 0) or 0 for i in active), "active_investigations": len([i for i in active if i.status != "watchlist"]),
                 "pending_approvals": pending, "recovery_success_rate": (sum(1 for r in decided if r["verdict"] == "recovered") / len(decided)) if decided else None,
                 "verified_outcomes": len(decided)},
        "issues_by_severity": [{"severity": k, "count": v} for k, v in sev.items()],
        "revenue_by_issue": [{"issue": i.code, "title": i.category, "revenue_at_risk": est.get(i.id, {}).get("revenue_at_risk", 0) or 0,
                              "affected": est.get(i.id, {}).get("affected_customers_measured", 0) or 0, "severity": i.severity} for i in confirmed],
        "recent_incidents": [issue_out(i) for i in recent],
        "trends": _kpi_series(db, ["complaint_volume", "csat", "delivery_success_rate", "payment_success_rate", "service_availability", "refund_completion_rate"]),
    }


@router.get("/impact/overview", summary="Cross-issue customer impact: segments, geography, revenue exposure")
def impact_overview(db: Session = Depends(get_db), _=Depends(get_current_user)):
    from app.agents.common import inv_state

    rows, geo, seg = [], {}, {}
    for i in db.scalars(select(DetectedIssue).where(DetectedIssue.status.not_in(["superseded", "watchlist"]))):
        e = {x.metric: x for x in db.scalars(select(BusinessImpactEstimate).where(BusinessImpactEstimate.issue_id == i.id, BusinessImpactEstimate.is_current.is_(True)))}
        s = inv_state(db, i.id).get("segmentation") or {}
        rows.append({"issue_id": i.id, "code": i.code, "category": i.category, "severity": i.severity, "affected": e["affected_customers_measured"].value if "affected_customers_measured" in e else 0,
                     "next_7d": e["affected_customers_next_7d"].value if "affected_customers_next_7d" in e else 0, "revenue_at_risk": e["revenue_at_risk"].value if "revenue_at_risk" in e else 0,
                     "retention_risk": e["retention_risk"].value if "retention_risk" in e else None, "business_severity": e["business_severity_score"].value if "business_severity_score" in e else None,
                     "revenue_exposure_30d": s.get("revenue_exposure_30d", 0)})
        for g in s.get("geography", []):
            c = geo.setdefault(g["value"], {"city": g["value"], "customers": g["customers"], "revenue_exposure_30d": 0.0})
            c[i.aspect] = g["affected"]
            c["revenue_exposure_30d"] += g["revenue_exposure_30d"]
        for p in s.get("predefined", []):
            c = seg.setdefault(p["value"], {"segment": p["value"], "name": p.get("name"), "customers": p["customers"], "revenue_exposure_30d": 0.0})
            c[i.aspect] = p["affected"]
            c["revenue_exposure_30d"] += p["revenue_exposure_30d"]
    return {"issues": rows, "geography": list(geo.values()), "segments": list(seg.values())}


# ----------------------------------------------------------------------------- monitoring
@router.get("/monitoring/overview", summary="KPI monitoring, intervention verification status and recovery timeline")
def monitoring(db: Session = Depends(get_db), _=Depends(get_current_user)):
    ver = _verification_results(db)
    ivs = []
    for iv in db.scalars(select(Intervention).where(Intervention.executed_at.is_not(None)).order_by(Intervention.executed_at.desc())):
        issue = db.get(DetectedIssue, iv.issue_id)
        meas = db.execute(select(RecoveryMeasurement.measured_on, RecoveryMeasurement.value, RecoveryMeasurement.phase, RecoveryKpi.code).join(RecoveryKpi, RecoveryKpi.id == RecoveryMeasurement.kpi_id)
                          .where(RecoveryMeasurement.intervention_id == iv.id).order_by(RecoveryMeasurement.measured_on)).all()
        ivs.append({**intervention_out(iv), "issue": {"id": issue.id, "code": issue.code, "title": issue.title, "status": issue.status, "kpi": issue.kpi_name},
                    "verification": ver.get(iv.id), "series": [{"date": d.isoformat(), "value": v, "phase": p, "kpi": c} for d, v, p, c in meas]})
    reopened = [issue_out(i) for i in db.scalars(select(DetectedIssue).where(DetectedIssue.reopen_count > 0))]
    timeline = []
    for iv in ivs:
        timeline.append({"at": iv["executed_at"], "kind": "executed", "title": f"{iv['code']} executed", "detail": iv["title"]})
        v = iv["verification"]
        if v:
            timeline.append({"at": iv["verified_at"] or iv["executed_at"], "kind": v["verdict"], "title": f"{iv['code']}: {v['verdict'].replace('_', ' ')}", "detail": v["explanation"]})
    timeline.sort(key=lambda x: x["at"] or "")
    return {"sim_now": get_sim_now(db).isoformat(), "kpis": _kpi_series(db), "interventions": ivs, "reopened_investigations": reopened, "timeline": timeline,
            "world_connected": world_sync.has_world(db)}


@router.post("/monitoring/advance", summary="Advance the simulated clock, ingest new data and verify executed interventions")
def advance(body: AdvanceIn, db: Session = Depends(get_db), user: User = Depends(analyst)):
    if not world_sync.has_world(db):
        raise HTTPException(409, "No simulated world is connected; load the sample datasets first")
    return pipeline.advance_and_verify(db, body.days, user.id)


@router.post("/monitoring/verify/{issue_id}", summary="Run recovery verification now for an issue")
def verify_now(issue_id: int, db: Session = Depends(get_db), user: User = Depends(analyst)):
    from app.agents import orchestrator

    if db.get(DetectedIssue, issue_id) is None:
        raise HTTPException(404, "Issue not found")
    ctx = Ctx(db, orchestrator.new_run_id(), issue_id)
    st = orchestrator.run_graph(ctx, issue_id, "verify", user.id)
    db.commit()
    return {"run_id": ctx.run_id, "errors": st.get("errors", []), "issue": issue_out(db.get(DetectedIssue, issue_id))}


# ----------------------------------------------------------------------------- scenarios
@router.get("/scenarios/schema", summary="Injection types and presets available to the jury simulator")
def scenario_schema(_=Depends(get_current_user)):
    return {"injections": scenarios.INJECTION_SCHEMA, "presets": [{"id": k, **{x: v[x] for x in ("label", "description", "injections")}} for k, v in scenarios.PRESETS.items()]}


@router.post("/scenarios/run", summary="Inject evidence, re-investigate and compare old vs new investigation")
def run_scenario(body: ScenarioIn, db: Session = Depends(get_db), user: User = Depends(analyst)):
    if db.get(DetectedIssue, body.issue_id) is None:
        raise HTTPException(404, "Issue not found")
    inj = [i.model_dump() for i in body.injections]
    name = body.name
    if body.preset:
        p = scenarios.PRESETS.get(body.preset)
        if not p:
            raise HTTPException(422, "Unknown preset")
        inj, name = p["injections"], name or p["label"]
    if not inj:
        raise HTTPException(422, "Provide a preset or at least one injection")
    try:
        scn = scenarios.run_scenario(db, body.issue_id, name or "Custom scenario", inj, user.id, body.preset or "custom")
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, str(exc))
    return scenario_out(scn)


def scenario_out(s: Scenario) -> dict:
    return {"id": s.id, "issue_id": s.issue_id, "name": s.name, "type": s.scenario_type, "status": s.status, "created_at": iso(s.created_at), "params": s.params,
            "injected": s.injected_summary, "before": s.before_snapshot, "after": s.after_snapshot, "diff": s.diff}


@router.get("/scenarios", summary="Previous scenarios")
def list_scenarios(issue_id: int | None = None, db: Session = Depends(get_db), _=Depends(get_current_user)):
    q = select(Scenario).order_by(Scenario.id.desc()).limit(50)
    if issue_id:
        q = select(Scenario).where(Scenario.issue_id == issue_id).order_by(Scenario.id.desc())
    return [{"id": s.id, "issue_id": s.issue_id, "name": s.name, "type": s.scenario_type, "status": s.status, "created_at": iso(s.created_at),
             "narrative": (s.diff or {}).get("narrative", "")[:240]} for s in db.scalars(q)]


@router.get("/scenarios/{scenario_id}", summary="Scenario with before / after snapshots and diff")
def get_scenario(scenario_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    s = db.get(Scenario, scenario_id)
    if s is None:
        raise HTTPException(404, "Scenario not found")
    return scenario_out(s)


# ----------------------------------------------------------------------------- evaluation
@router.get("/evaluation", summary="AI evaluation against the hidden benchmark ground truth")
def evaluate(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return evaluation.compute(db)


# ----------------------------------------------------------------------------- system
@router.get("/health", summary="Liveness probe", tags=["System"])
def health():
    return {"status": "ok"}


@router.get("/system/info", summary="Deployment information", tags=["System"])
def system_info(db: Session = Depends(get_db), _=Depends(get_current_user)):
    s = get_settings()
    st = "sentence-transformers (MiniLM)" if importlib.util.find_spec("sentence_transformers") and s.embedding_backend != "tfidf" else "tfidf-svd"
    return {"app": s.app_name, "environment": s.environment, "database": get_engine().dialect.name, "sim_now": get_sim_now(db).isoformat(), "llm_provider": s.llm_provider,
            "llm_enabled": s.llm_enabled, "llm_model": s.llm_model if s.llm_enabled else None, "embedding_backend": st, "demo_mode": s.demo_mode,
            "world_connected": world_sync.has_world(db), "data_retention_days": s.data_retention_days, "data_label": "All demo data is simulated"}


@router.post("/system/reset-demo", summary="Wipe analytical data and reload the simulated demo dataset (admin)", tags=["System"])
def reset_demo(tasks: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(admin)):
    with pipeline.LOCK:
        for t in reversed(Base.metadata.sorted_tables):
            if t.name not in ("users", "roles"):
                db.execute(t.delete())
        db.commit()
        reports = seed.seed_demo(db)
        audit(db, user.id, "system.reset_demo", "system", None, {})
        db.commit()
    if get_settings().auto_run_analysis and reports:
        tasks.add_task(run_in_background, pipeline.run_full_analysis, user.id)
    return {"status": "reset", "loaded": {k: v["inserted"] for k, v in (reports or {}).items()}}


@router.post("/system/retention/purge", summary="Delete evidence older than N days (data retention control, admin)", tags=["System"])
def purge(body: RetentionIn, db: Session = Depends(get_db), user: User = Depends(admin)):
    cutoff = get_sim_now(db) - timedelta(days=body.days)
    ids = [i for (i,) in db.execute(select(CustomerSignal.id).where(CustomerSignal.occurred_at < cutoff))]
    for k in range(0, len(ids), 500):
        chunk = ids[k:k + 500]
        db.execute(delete(IssueEvidence).where(IssueEvidence.signal_id.in_(chunk)))
        db.execute(update(HypothesisEvidence).where(HypothesisEvidence.signal_id.in_(chunk)).values(signal_id=None))
        db.execute(delete(CustomerSignal).where(CustomerSignal.id.in_(chunk)))
    audit(db, user.id, "retention.purge", "system", None, {"cutoff": cutoff.isoformat(), "deleted": len(ids)})
    db.commit()
    return {"cutoff": cutoff.isoformat(), "deleted_signals": len(ids)}


@router.get("/notifications", summary="Notification centre", tags=["System"])
def notifications(db: Session = Depends(get_db), _=Depends(get_current_user)):
    rows = list(db.scalars(select(Notification).order_by(Notification.id.desc()).limit(40)))
    return {"unread": sum(1 for r in rows if not r.is_read), "items": [{"id": r.id, "level": r.level, "title": r.title, "body": r.body, "link": r.link, "is_read": r.is_read,
                                                                        "created_at": iso(r.created_at)} for r in rows]}


@router.post("/notifications/read", summary="Mark all notifications as read", tags=["System"])
def read_notifications(db: Session = Depends(get_db), _=Depends(get_current_user)):
    db.execute(update(Notification).values(is_read=True))
    db.commit()
    return {"status": "ok"}


@router.get("/audit-logs", summary="Audit trail (approver / admin)", tags=["System"])
def audit_logs(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db), _=Depends(approver)):
    users = {u.id: u.email for u in db.scalars(select(User))}
    return [{"id": a.id, "at": iso(a.created_at), "user": users.get(a.user_id), "action": a.action, "entity_type": a.entity_type, "entity_id": a.entity_id, "detail": a.detail,
             "ip": a.ip_address} for a in db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit))]


@router.get("/search", summary="Global search across issues, hypotheses, interventions and evidence", tags=["System"])
def global_search(q: str = Query(min_length=2, max_length=100), db: Session = Depends(get_db), _=Depends(get_current_user)):
    like = f"%{q}%"
    issues = [{"type": "issue", "id": i.id, "title": f"{i.code} - {i.title}", "link": f"/investigations/{i.id}"} for i in
              db.scalars(select(DetectedIssue).where(or_(DetectedIssue.title.ilike(like), DetectedIssue.code.ilike(like), DetectedIssue.category.ilike(like))).limit(5))]
    hyps = [{"type": "hypothesis", "id": h.id, "title": h.title, "link": f"/investigations/{h.issue_id}"} for h in
            db.scalars(select(RootCauseHypothesis).where(RootCauseHypothesis.is_current.is_(True), RootCauseHypothesis.title.ilike(like)).limit(5))]
    ivs = [{"type": "intervention", "id": i.id, "title": f"{i.code} - {i.title}", "link": "/interventions"} for i in
           db.scalars(select(Intervention).where(Intervention.superseded.is_(False), or_(Intervention.title.ilike(like), Intervention.code.ilike(like))).limit(5))]
    sigs = [{"type": "evidence", "id": s.id, "title": (s.text or s.external_id)[:90], "link": f"/signals?q={q}"} for s in
            db.scalars(select(CustomerSignal).where(CustomerSignal.is_current.is_(True), CustomerSignal.text.ilike(like)).limit(5))]
    return {"results": issues + hyps + ivs + sigs}
