"""Evidence validation checkpoint used by the orchestrator (not one of the eight domain agents)."""
from __future__ import annotations

from sqlalchemy import select

from app.agents.context import AgentResult, Ctx
from app.models import RootCauseHypothesis
from app.services.evidence import groundedness


def run(ctx: Ctx, issue_id: int) -> AgentResult:
    db = ctx.db
    g = groundedness(db, ctx.view, issue_id)
    hyps = list(db.scalars(select(RootCauseHypothesis).where(RootCauseHypothesis.issue_id == issue_id, RootCauseHypothesis.is_current.is_(True)).order_by(RootCauseHypothesis.rank)))
    problems = []
    if g["ratio"] < 0.95:
        problems.append(f"{len(g['ungrounded'])} evidence item(s) could not be reproduced from the data")
    for h in hyps:
        sup = [e for e in h.evidence if e.relation == "supports" and e.kind == "statistic"]
        if h.confidence > 0.5 and not sup:
            problems.append(f"hypothesis '{h.title}' has confidence {h.confidence:.0%} without any supporting statistic")
        if h.confidence > 0.9:
            problems.append(f"hypothesis '{h.title}' exceeds the confidence cap")
    ok = not problems and bool(hyps)
    if not hyps:
        problems.append("no hypotheses were produced")
    return AgentResult(output={"ok": ok, "groundedness": round(g["ratio"], 4), "checked": g["checked"], "problems": problems},
                       reasoning=(f"Recomputed {g['checked']} checkable evidence claims; {g['grounded']} reproduced exactly ({g['ratio']:.0%}). " + ("Validation passed." if ok else "Validation failed: " + "; ".join(problems))),
                       inputs={"hypotheses": len(hyps)})
