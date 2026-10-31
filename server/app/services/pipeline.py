"""High-level workflows that drive the orchestrator (detection, investigation, execution, verification)."""
from __future__ import annotations

import logging
import threading

from sqlalchemy import select

from app.agents import issue_agent, orchestrator, signal_agent
from app.agents.common import get_investigation
from app.agents.context import Ctx
from app.models import DetectedIssue, Intervention
from app.services import world_sync
from app.services.system import audit, notify

log = logging.getLogger("cx.pipeline")
LOCK = threading.RLock()


def run_detection(db, user_id: int | None = None) -> dict:
    with LOCK:
        ctx = Ctx(db, orchestrator.new_run_id())
        _, e1 = orchestrator.record(ctx, "Signal Intelligence Agent", "Audit and normalise multi-source evidence", None, lambda: signal_agent.run(ctx))
        ctx.refresh_view()
        res, e2 = orchestrator.record(ctx, "Emerging Issue Detection Agent", "Cluster complaints and test against historical baselines", None, lambda: issue_agent.run(ctx))
        if e1 or e2:
            raise RuntimeError(f"Detection failed: {e1 or e2}")
        for i in res.output.get("issues", []):
            get_investigation(db, i["id"])
        issues = res.output.get("issues", [])
        notify(db, f"{len(issues)} issue(s) detected", ", ".join(i["code"] + " " + i["severity"] for i in issues[:5]), "warning" if issues else "info", "/issues")
        audit(db, user_id, "detection.run", "system", None, {"issues": [i["code"] for i in issues]})
        db.commit()
        return {"run_id": ctx.run_id, **res.output}


def investigate(db, issue_id: int, trigger: str = "investigate", user_id: int | None = None) -> dict:
    with LOCK:
        ctx = Ctx(db, orchestrator.new_run_id(), issue_id)
        st = orchestrator.run_graph(ctx, issue_id, trigger, user_id)
        issue = db.get(DetectedIssue, issue_id)
        audit(db, user_id, f"investigation.{trigger}", "issue", issue_id, {"run_id": ctx.run_id, "status": issue.status})
        db.commit()
        return {"run_id": ctx.run_id, "issue_id": issue_id, "status": issue.status, "errors": st.get("errors", []), "steps": st.get("steps")}


def run_full_analysis(db, user_id: int | None = None) -> dict:
    with LOCK:
        det = run_detection(db, user_id)
        out = []
        for i in det.get("issues", []):
            issue = db.get(DetectedIssue, i["id"])
            if issue.status in ("open", "reopened"):
                out.append(investigate(db, i["id"], "investigate", user_id))
        notify(db, "Analysis complete", f"{len(out)} investigation(s) finished.", "success", "/")
        db.commit()
        return {"detection": det, "investigations": out}


def execute_approved(db, intervention_id: int, user_id: int | None = None) -> dict:
    """Resume the graph after a human approval: execute the approved intervention, then check for verification."""
    with LOCK:
        iv = db.get(Intervention, intervention_id)
        ctx = Ctx(db, orchestrator.new_run_id(), iv.issue_id)
        st = orchestrator.run_graph(ctx, iv.issue_id, "resume", user_id, only_intervention=intervention_id)
        db.refresh(iv)
        return {"run_id": ctx.run_id, "intervention": iv.code, "status": iv.status, "errors": st.get("errors", [])}


def advance_and_verify(db, days: int, user_id: int | None = None) -> dict:
    """Advance the simulated clock, ingest the new world data, then verify every executed root-cause intervention."""
    with LOCK:
        adv = world_sync.advance(db, days, user_id)
        db.commit()
        verified = []
        reopened = []
        issue_ids = {iv.issue_id for iv in db.scalars(select(Intervention).where(Intervention.status == "executed", Intervention.role == "root_cause_fix",
                                                                                 Intervention.verification_status.in_(["monitoring", "partial", "insufficient_data", "not_started"])))}
        for iid in issue_ids:
            ctx = Ctx(db, orchestrator.new_run_id(), iid)
            orchestrator.run_graph(ctx, iid, "verify", user_id)
            issue = db.get(DetectedIssue, iid)
            verified.append({"issue_id": iid, "status": issue.status})
            if issue.status == "reopened":
                orchestrator.run_graph(Ctx(db, orchestrator.new_run_id(), iid), iid, "reinvestigate", user_id)
                reopened.append(iid)
        audit(db, user_id, "simulation.advance", "system", None, {"days": days})
        db.commit()
        return {**adv, "verified": verified, "reopened": reopened}
