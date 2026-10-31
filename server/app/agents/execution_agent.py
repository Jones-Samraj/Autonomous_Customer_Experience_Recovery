"""Agent 7 - Recovery Execution.

Runs approved interventions through simulated enterprise tools with idempotency keys, bounded retries with back-off,
failure logging and compensating rollback. Never executes anything that is not in the ``approved`` state.
"""
from __future__ import annotations

import logging
import time

from sqlalchemy import select

from app.agents.context import AgentResult, Ctx
from app.agents.domain import INTERVENTIONS
from app.db import utcnow
from app.models import ExecutionLog, Intervention
from app.services.system import audit, get_sim_now, notify
from app.tools.enterprise import PermanentToolError, TOOLS, TransientToolError, maybe_fail

log = logging.getLogger("cx.exec")


def _log(db, iv, tool, key, attempt, status, request, response=None, error=None, ms=0):
    db.add(ExecutionLog(intervention_id=iv.id, action=tool, simulated_system=TOOLS[tool][2], idempotency_key=key, attempt=attempt, status=status,
                        request=request, response=response, error=error, duration_ms=ms))
    db.flush()


def _already_done(db, key: str) -> ExecutionLog | None:
    return db.scalar(select(ExecutionLog).where(ExecutionLog.idempotency_key == key, ExecutionLog.status == "success").order_by(ExecutionLog.id.desc()))


def execute(ctx: Ctx, intervention_id: int, user_id: int | None = None) -> AgentResult:
    db = ctx.db
    iv = db.get(Intervention, intervention_id)
    if iv.status not in ("approved", "failed"):
        raise PermissionError(f"Intervention {iv.code} is '{iv.status}', only approved interventions can be executed")
    spec = INTERVENTIONS[iv.intervention_type]
    done: list[str] = []
    results = []
    for tool in spec["tools"]:
        key = f"{iv.code}:{tool}"
        prior = _already_done(db, key)
        if prior:
            _log(db, iv, tool, key, 0, "skipped", {"reason": "idempotent replay"}, prior.response)
            results.append({"tool": tool, "status": "skipped (idempotent)", "response": prior.response})
            done.append(tool)
            continue
        request = {"intervention": iv.code, "type": iv.intervention_type, "department": (iv.params or {}).get("department"), "units": (iv.params or {}).get("units")}
        ok, resp, err = False, None, None
        for attempt in range(1, ctx.s.tool_max_retries + 1):
            t0 = time.time()
            try:
                maybe_fail(ctx.s, key, attempt)
                resp = TOOLS[tool][0](db, iv, request)
                _log(db, iv, tool, key, attempt, "success", request, resp, None, int((time.time() - t0) * 1000))
                ok = True
                break
            except TransientToolError as exc:
                err = str(exc)
                _log(db, iv, tool, key, attempt, "retrying" if attempt < ctx.s.tool_max_retries else "failed", request, None, err, int((time.time() - t0) * 1000))
                time.sleep(0.02 * attempt)
            except PermanentToolError as exc:
                err = str(exc)
                _log(db, iv, tool, key, attempt, "failed", request, None, err, int((time.time() - t0) * 1000))
                break
        if not ok:
            for t_done in reversed(done):  # compensate what already succeeded
                try:
                    comp = TOOLS[t_done][1](db, iv, {})
                    _log(db, iv, t_done, f"{iv.code}:{t_done}:rollback", 1, "rolled_back", {"reason": f"{tool} failed"}, comp)
                except Exception as exc:  # noqa: BLE001
                    _log(db, iv, t_done, f"{iv.code}:{t_done}:rollback", 1, "failed", {"reason": "compensation error"}, None, str(exc))
            iv.status = "failed"
            db.flush()
            notify(db, f"Execution failed: {iv.code}", f"{tool} failed after retries: {err}", "error", "/approvals")
            audit(db, user_id, "intervention.execute_failed", "intervention", iv.id, {"tool": tool, "error": err})
            return AgentResult(output={"intervention": iv.code, "status": "failed", "failed_tool": tool, "error": err, "compensated": list(reversed(done))},
                               reasoning=f"{tool} failed after {ctx.s.tool_max_retries} attempts ({err}); completed steps were rolled back and the intervention was marked failed.",
                               inputs={"intervention": iv.code}, status="failed")
        results.append({"tool": tool, "status": "success", "response": resp})
        done.append(tool)
    iv.status = "executed"
    iv.executed_at = get_sim_now(db)
    iv.verification_status = "monitoring" if iv.role == "root_cause_fix" else "not_applicable"
    db.flush()
    notify(db, f"Intervention executed: {iv.code}", f"{iv.title}. Monitoring KPIs to verify recovery.", "success", "/monitoring")
    audit(db, user_id, "intervention.execute", "intervention", iv.id, {"tools": [r["tool"] for r in results]})
    return AgentResult(output={"intervention": iv.code, "status": "executed", "steps": results},
                       reasoning=f"Executed {len(results)} tool call(s) for {iv.code} via simulated enterprise systems; execution does not mean recovery - verification is pending.",
                       inputs={"intervention": iv.code, "tools": spec["tools"]})


def rollback(ctx: Ctx, intervention_id: int, user_id: int | None = None) -> AgentResult:
    db = ctx.db
    iv = db.get(Intervention, intervention_id)
    if iv.status != "executed":
        raise PermissionError("Only executed interventions can be rolled back")
    spec = INTERVENTIONS[iv.intervention_type]
    steps = []
    for tool in reversed(spec["tools"]):
        comp = TOOLS[tool][1](db, iv, {})
        _log(db, iv, tool, f"{iv.code}:{tool}:rollback", 1, "rolled_back", {"reason": "manual rollback"}, comp)
        steps.append({"tool": tool, "result": comp})
    iv.status, iv.rolled_back_at, iv.verification_status = "rolled_back", utcnow(), "not_applicable"
    db.flush()
    notify(db, f"Intervention rolled back: {iv.code}", iv.title, "warning", "/approvals")
    audit(db, user_id, "intervention.rollback", "intervention", iv.id, {"steps": steps})
    return AgentResult(output={"intervention": iv.code, "status": "rolled_back", "steps": steps},
                       reasoning=f"Rolled back {iv.code} using compensating actions for each executed tool.", inputs={"intervention": iv.code})
