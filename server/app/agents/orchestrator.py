"""LangGraph orchestration of the eight agents.

Hub-and-spoke graph: a *supervisor* node inspects the persisted investigation state (issue, hypotheses, interventions,
approvals) and conditionally routes to the next agent. Every agent node records an execution-history entry, retries on
failure, and hands control back to the supervisor. The human approval checkpoint ends a run in ``awaiting_approval``;
approving an intervention resumes the graph from the persisted state.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select

from app.agents import (execution_agent, impact_agent, intervention_agent, issue_agent, rootcause_agent, segment_agent, signal_agent, validation,
                        verification_agent)
from app.agents.common import get_investigation
from app.agents.context import AgentResult, Ctx
from app.core.events import publish
from app.db import utcnow
from app.models import AgentExecutionHistory, ApprovalRequest, DetectedIssue, Intervention

log = logging.getLogger("cx.orchestrator")
MAX_RETRIES = 1
MAX_STEPS = 40


class InvState(TypedDict, total=False):
    issue_id: int
    run_id: str
    trigger: str
    completed: list
    next: str
    status: str
    retries: dict
    errors: list
    steps: int
    validation_failed: bool
    only_intervention: int | None
    user_id: int | None


SEQUENCES = {
    "investigate": ["signal_intelligence", "segmentation", "root_cause", "evidence_validation", "impact", "intervention_planning", "recovery_execution"],
    "new_evidence": ["signal_intelligence", "issue_detection", "segmentation", "root_cause", "evidence_validation", "impact", "intervention_planning", "recovery_execution"],
    "reinvestigate": ["root_cause", "evidence_validation", "impact", "intervention_planning", "recovery_execution"],
    "resume": ["recovery_execution"],
    "verify": ["verification"],
}

LABEL = {
    "signal_intelligence": ("Signal Intelligence Agent", "Audit and normalise multi-source evidence"),
    "issue_detection": ("Emerging Issue Detection Agent", "Cluster complaints and test against historical baselines"),
    "segmentation": ("Customer Segmentation Agent", "Identify impacted customer groups"),
    "root_cause": ("Root Cause Investigation Agent", "Generate and score competing root-cause hypotheses"),
    "evidence_validation": ("Evidence Validator", "Recompute evidence claims and check groundedness"),
    "impact": ("Business Impact Assessment Agent", "Estimate customers, revenue and cost impact with ranges"),
    "intervention_planning": ("Intervention Planning Agent", "Generate and rank recovery strategies"),
    "recovery_execution": ("Recovery Execution Agent", "Execute approved interventions via enterprise tools"),
    "verification": ("Verification & Learning Agent", "Verify KPI recovery after intervention"),
}


def _safe(obj):
    return json.loads(json.dumps(obj, default=str))


def record(ctx: Ctx, agent: str, task: str, issue_id: int | None, fn, attempt: int = 1) -> tuple[AgentResult | None, Exception | None]:
    """Run ``fn`` and persist an agent-execution-history row either way."""
    db = ctx.db
    started = utcnow()
    before = ctx.llm.snapshot()
    t0 = time.time()
    fields: dict = {"run_id": ctx.run_id, "issue_id": issue_id, "agent": agent, "task": task, "attempt": attempt, "started_at": started}
    try:
        res = fn()
        fields.update(input_summary=_safe({**res.inputs, "sim_now": ctx.now.isoformat()}), output_summary=_safe(res.output),
                      reasoning_summary=res.reasoning, status=res.status)
        err = None
    except Exception as exc:  # noqa: BLE001
        db.rollback()  # discard the agent's partial writes; the history row below is written in a fresh transaction
        fields.update(input_summary={"sim_now": ctx.now.isoformat()}, status="failed", error=f"{exc.__class__.__name__}: {exc}")
        res, err = None, exc
        log.exception("agent %s failed", agent)
    after = ctx.llm.snapshot()
    hist = AgentExecutionHistory(**fields, finished_at=utcnow(), duration_ms=int((time.time() - t0) * 1000), llm_tokens_in=after[0] - before[0],
                                 llm_tokens_out=after[1] - before[1], llm_cost_usd=after[2] - before[2])
    db.add(hist)
    db.commit()
    publish({"type": "agent_event", "agent": agent, "status": hist.status, "issue_id": issue_id, "run_id": ctx.run_id, "task": task})
    return res, err


def _unexecuted_approved(db, issue_id: int, only: int | None):
    q = select(Intervention).where(Intervention.issue_id == issue_id, Intervention.status == "approved", Intervention.superseded.is_(False))
    if only:
        q = q.where(Intervention.id == only)
    return list(db.scalars(q))


def _pending(db, issue_id: int) -> bool:
    return db.scalar(select(ApprovalRequest.id).join(Intervention, Intervention.id == ApprovalRequest.intervention_id).where(
        Intervention.issue_id == issue_id, ApprovalRequest.status == "pending", Intervention.superseded.is_(False)).limit(1)) is not None


def _awaiting_verification(db, issue_id: int) -> bool:
    return db.scalar(select(Intervention.id).where(Intervention.issue_id == issue_id, Intervention.status == "executed", Intervention.role == "root_cause_fix",
                                                   Intervention.verification_status.in_(["monitoring", "partial", "insufficient_data", "not_started"])).limit(1)) is not None


def build_graph(ctx: Ctx):
    db = ctx.db

    def plan_next(st: InvState) -> tuple[str, str]:
        if st.get("status") == "failed":
            return "end", "An agent failed after retries; stopping the run."
        if st.get("steps", 0) >= MAX_STEPS:
            return "end", "Step limit reached; stopping to avoid a loop."
        done = set(st.get("completed", []))
        issue = db.get(DetectedIssue, st["issue_id"])
        for node in SEQUENCES[st["trigger"]]:
            if node in done:
                continue
            if node == "recovery_execution" and not _unexecuted_approved(db, issue.id, st.get("only_intervention")):
                continue
            if node == "verification" and not _awaiting_verification(db, issue.id):
                continue
            why = {
                "signal_intelligence": "Evidence has not been profiled in this run.",
                "issue_detection": "New evidence arrived, so issue statistics and severity must be recomputed.",
                "segmentation": "Affected customer groups have not been identified for this iteration.",
                "root_cause": "Root-cause hypotheses must be (re)generated for iteration %d." % issue.iteration,
                "evidence_validation": "Hypotheses were produced and need groundedness checks before use.",
                "impact": "Business impact must reflect the latest hypotheses and segments.",
                "intervention_planning": "Interventions must be ranked against the current hypothesis confidences.",
                "recovery_execution": "Approved interventions are waiting to be executed.",
                "verification": "An executed intervention is awaiting KPI verification.",
            }[node]
            return node, why
        return "end", "All applicable stages for this trigger are complete."

    def supervisor(state: InvState) -> dict:
        st = dict(state)
        if ctx.flags.pop("reopen", False) and st["trigger"] != "reinvestigate":
            st.update(trigger="reinvestigate", completed=[], validation_failed=False)
            reason_prefix = "Verification failed, investigation re-opened. "
        else:
            reason_prefix = ""
        if st.get("validation_failed") and "evidence_validation" in st.get("completed", []):
            if st.get("retries", {}).get("root_cause", 0) < 1:
                st["retries"] = {**st.get("retries", {}), "root_cause": 1}
                st["completed"] = [c for c in st["completed"] if c not in ("root_cause", "evidence_validation")]
                st["validation_failed"] = False
                ctx.flags["widen_lookback"] = True
                reason_prefix = "Evidence validation failed; widening the look-back window and re-running root-cause analysis. "
        nxt, why = plan_next(st)
        st["steps"] = st.get("steps", 0) + 1
        st["next"] = nxt
        agent = "Orchestrator (Supervisor)"
        db.add(AgentExecutionHistory(run_id=ctx.run_id, issue_id=st["issue_id"], agent=agent, task="Route to next agent", status="succeeded", started_at=utcnow(), finished_at=utcnow(),
                                     duration_ms=0, input_summary={"trigger": st["trigger"], "completed": st.get("completed", [])},
                                     reasoning_summary=reason_prefix + (f"Next: {LABEL[nxt][0]}. {why}" if nxt != "end" else why),
                                     output_summary={"next": nxt}))
        db.commit()
        if nxt == "end":
            st["status"] = st.get("status") or "completed"
            _finalize(ctx, st)
        return st

    def make_node(name: str):
        agent, task = LABEL[name]

        def node(state: InvState) -> dict:
            st = dict(state)
            iid = st["issue_id"]
            attempt = st.get("retries", {}).get(name, 0) + 1

            def call() -> AgentResult:
                if name == "signal_intelligence":
                    return signal_agent.run(ctx)
                if name == "issue_detection":
                    return issue_agent.run(ctx)
                if name == "segmentation":
                    return segment_agent.run(ctx, iid)
                if name == "root_cause":
                    return rootcause_agent.run(ctx, iid)
                if name == "evidence_validation":
                    return validation.run(ctx, iid)
                if name == "impact":
                    return impact_agent.run(ctx, iid)
                if name == "intervention_planning":
                    return intervention_agent.run(ctx, iid)
                if name == "verification":
                    return verification_agent.run(ctx, iid)
                results = [execution_agent.execute(ctx, iv.id, st.get("user_id")) for iv in _unexecuted_approved(db, iid, st.get("only_intervention"))]
                bad = [r for r in results if r.status == "failed"]
                return AgentResult(output={"executions": [r.output for r in results]}, reasoning=" ".join(r.reasoning for r in results),
                                   inputs={"interventions": [r.output.get("intervention") for r in results]}, status="failed" if bad else "succeeded")

            res, err = record(ctx, agent, task, iid, call, attempt)
            st["completed"] = list(st.get("completed", []))
            if err is not None:
                st["retries"] = {**st.get("retries", {}), name: attempt}
                st["errors"] = list(st.get("errors", [])) + [f"{agent}: {err}"]
                if attempt > MAX_RETRIES:
                    st["status"] = "failed"
            else:
                st["completed"].append(name)
                if name == "evidence_validation":
                    st["validation_failed"] = not res.output.get("ok", True)
                if name in ("issue_detection", "signal_intelligence"):
                    ctx.refresh_view()
                if name in ("recovery_execution", "root_cause", "segmentation", "intervention_planning", "impact"):
                    ctx.refresh_view()
                if name == "recovery_execution" and res.status == "failed":
                    st["errors"] = list(st.get("errors", [])) + ["Execution failed - see execution log"]
            return st

        return node

    g = StateGraph(InvState)
    g.add_node("supervisor", supervisor)
    nodes = list(LABEL)
    for n in nodes:
        g.add_node(n, make_node(n))
        g.add_edge(n, "supervisor")
    g.add_edge(START, "supervisor")
    g.add_conditional_edges("supervisor", lambda s: s["next"], {**{n: n for n in nodes}, "end": END})
    return g.compile()


def _finalize(ctx: Ctx, st: InvState) -> None:
    db = ctx.db
    issue = db.get(DetectedIssue, st["issue_id"])
    inv = get_investigation(db, issue.id)
    if st.get("status") == "failed":
        inv.status, inv.stage = "failed", "failed"
    elif _pending(db, issue.id):
        issue.status, inv.status, inv.stage = "awaiting_approval", "awaiting_approval", "awaiting_human_approval"
    elif _awaiting_verification(db, issue.id) and issue.status != "reopened":
        issue.status, inv.status, inv.stage = "monitoring", "monitoring", "monitoring"
    elif issue.status == "resolved":
        inv.status, inv.stage = "resolved", "verified"
    else:
        issue.status, inv.status, inv.stage = "investigating", "completed", "plan_ready"
    inv.iteration = issue.iteration
    inv.updated_at = utcnow()
    db.commit()
    publish({"type": "investigation_update", "issue_id": issue.id, "status": issue.status, "stage": inv.stage})


def run_graph(ctx: Ctx, issue_id: int, trigger: str, user_id: int | None = None, only_intervention: int | None = None) -> InvState:
    graph = build_graph(ctx)
    db = ctx.db
    inv = get_investigation(db, issue_id)
    issue = db.get(DetectedIssue, issue_id)
    if trigger in ("investigate", "new_evidence", "reinvestigate"):
        inv.status, inv.stage = "running", "investigating"
        if issue.status in ("open", "watchlist", "reopened"):
            issue.status = "investigating"
    db.commit()
    init: InvState = {"issue_id": issue_id, "run_id": ctx.run_id, "trigger": trigger, "completed": [], "retries": {}, "errors": [], "steps": 0,
                      "validation_failed": False, "only_intervention": only_intervention, "user_id": user_id, "status": ""}
    return graph.invoke(init, {"recursion_limit": 120})


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]
