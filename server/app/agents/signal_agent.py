"""Agent 1 - Signal Intelligence: audit the normalised evidence store (coverage, freshness, reliability, gaps)."""
from __future__ import annotations

import pandas as pd
from sqlalchemy import func, select

from app.agents.context import AgentResult, Ctx
from app.agents.domain import ASPECT_CAUSES
from app.models import CustomerSignal, DataSource
from app.services import nlp
from app.services.system import set_setting

VOICE = ["review", "ticket", "social", "survey"]


def run(ctx: Ctx) -> AgentResult:
    db = ctx.db
    rows = db.execute(select(CustomerSignal.source_type, func.count(), func.avg(CustomerSignal.reliability), func.min(CustomerSignal.occurred_at),
                             func.max(CustomerSignal.occurred_at)).where(CustomerSignal.is_current.is_(True)).group_by(CustomerSignal.source_type)).all()
    by_type = {r[0]: {"count": int(r[1]), "reliability": round(float(r[2] or 0), 2), "first": r[3].isoformat(), "last": r[4].isoformat()} for r in rows}
    flagged = db.scalar(select(func.count()).select_from(CustomerSignal).where(CustomerSignal.is_current.is_(True), CustomerSignal.is_flagged.is_(True))) or 0
    injected = db.scalar(select(func.count()).select_from(CustomerSignal).where(CustomerSignal.is_current.is_(True), CustomerSignal.is_injected.is_(True))) or 0
    revisions = db.scalar(select(func.count()).select_from(CustomerSignal).where(CustomerSignal.is_current.is_(False))) or 0

    unnormalised = list(db.scalars(select(CustomerSignal).where(CustomerSignal.is_current.is_(True), CustomerSignal.source_type.in_(VOICE),
                                                                CustomerSignal.sentiment.is_(None), CustomerSignal.text.is_not(None))))
    for s in unnormalised:
        clean, flag, reason = nlp.sanitize_untrusted(s.text)
        s.text, s.is_flagged, s.flag_reason = clean, flag, reason
        s.sentiment = nlp.sentiment(clean)
        s.primary_aspect, s.aspects = nlp.primary_aspect(clean)
    db.flush()

    present_metrics = set(ctx.view.metrics()["metric_name"].unique()) if not ctx.view.metrics().empty else set()
    wanted = {t["metric"] for ts in ASPECT_CAUSES.values() for t in ts if t.get("metric")}
    gaps = sorted(wanted - present_metrics)
    last = max((pd.Timestamp(v["last"]) for v in by_type.values()), default=None)
    freshness_h = round((pd.Timestamp(ctx.now) - last).total_seconds() / 3600, 1) if last is not None else None
    sources = [{"id": s.id, "name": s.name, "type": s.source_type, "reliability": s.reliability, "simulated": s.is_simulated, "records": s.record_count}
               for s in db.scalars(select(DataSource))]
    profile = {"as_of": ctx.now.isoformat(), "by_source_type": by_type, "flagged_prompt_injection": int(flagged), "scenario_injected": int(injected),
               "superseded_revisions": int(revisions), "renormalised": len(unnormalised), "data_gaps": gaps, "freshness_hours": freshness_h,
               "sources": sources}
    set_setting(db, "data_profile", profile)
    total = sum(v["count"] for v in by_type.values())
    reasoning = (f"Audited {total} current evidence records across {len(by_type)} source types; {flagged} customer texts were neutralised as "
                 f"instruction-like content and excluded from analytics; {len(gaps)} diagnostic metric(s) are not connected"
                 + (f" ({', '.join(gaps)})" if gaps else "") + ".")
    return AgentResult(output={k: v for k, v in profile.items() if k != "sources"}, reasoning=reasoning,
                       inputs={"sources": len(sources), "as_of": ctx.now.isoformat()})
