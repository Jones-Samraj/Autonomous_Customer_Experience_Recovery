"""Agent 8 - Verification and Learning.

Executing an action never counts as recovery. This agent compares the structured KPI of cohorts that started *after* the
intervention took effect against the pre-intervention cohort (two-proportion test) and against the historical baseline.
Failure re-opens the investigation; the failed cause is down-weighted by the root-cause agent on the next iteration.
"""
from __future__ import annotations

import pandas as pd
from scipy.stats import norm
from sqlalchemy import delete, select

from app.agents.common import get_investigation
from app.agents.context import AgentResult, Ctx
from app.analytics import stats
from app.db import utcnow
from app.models import DetectedIssue, Intervention, RecoveryMeasurement
from app.services.kpis import daily_kpis, ensure_kpis
from app.services.system import notify

MIN_POST_N = 60
PRIMARY_KPI = {"late_delivery_rate": "delivery_success_rate", "payment_failure_rate": "payment_success_rate", "crash_rate": "service_availability",
               "refund_sla_breach_rate": "refund_completion_rate"}
SECONDARY = {"complaint_volume": "lower", "csat": "higher", "resolution_time_hours": "lower", "repeat_complaint_rate": "lower", "customer_retention": "higher"}


def _verify_one(ctx: Ctx, issue: DetectedIssue, iv: Intervention) -> dict:
    view = ctx.view
    f = view.kpi_frame(issue.kpi_name)
    exec_ts = pd.Timestamp(iv.executed_at)
    exec_day = exec_ts.normalize()
    eff_day = (exec_ts + pd.Timedelta(hours=iv.execution_hours or 0)).ceil("D")
    pre = f[(f["date"] >= exec_day - pd.Timedelta(days=7)) & (f["date"] < exec_day)]
    post = f[f["date"] >= eff_day]
    base_end = pd.Timestamp(view.w.baseline_end)
    base = f[f["date"] < base_end]
    p0 = base["k"].sum() / max(base["n"].sum(), 1)
    n_pre, k_pre, n_post, k_post = pre["n"].sum(), pre["k"].sum(), post["n"].sum(), post["k"].sum()
    days_post = int(post["date"].nunique())
    res = {"intervention": iv.code, "intervention_id": iv.id, "kpi": issue.kpi_name, "executed_on": str(exec_day.date()), "effective_from": str(eff_day.date()),
           "pre": {"n": int(n_pre), "k": int(k_pre), "rate": float(k_pre / n_pre) if n_pre else None},
           "post": {"n": int(n_post), "k": int(k_post), "rate": float(k_post / n_post) if n_post else None, "days": days_post},
           "baseline_rate": float(p0)}
    if n_post < MIN_POST_N or days_post < 2 or n_pre < 20:
        res.update(verdict="insufficient_data", explanation=f"Only {int(n_post)} post-intervention records over {days_post} day(s) are available; advance the clock to collect more evidence before judging recovery.")
        return res
    r_pre, r_post = k_pre / n_pre, k_post / n_post
    z, _ = stats.two_prop_z(k_pre, n_pre, k_post, n_post)
    p_improve = float(norm.sf(z))
    band = p0 + 0.25 * max(r_pre - p0, 0)
    rel = (r_pre - r_post) / r_pre if r_pre > 0 else 0.0
    lo, hi = stats.wilson(k_post, n_post)
    in_band = r_post <= band or hi <= band * 1.15
    res.update(z=float(z), p_improvement=p_improve, relative_improvement=float(rel), recovery_band_max=float(band), post_ci=[lo, hi])
    if in_band and (p_improve is None or p_improve < 0.05):
        verdict = "recovered"
        expl = f"{issue.kpi_name.replace('_', ' ')} fell from {r_pre:.1%} to {r_post:.1%} (back within the recovery band of {band:.1%}; baseline {p0:.1%}). The improvement is statistically significant (p={p_improve:.3f})."
    elif p_improve is not None and p_improve < 0.05 and rel >= 0.3:
        verdict = "partial"
        expl = f"{issue.kpi_name.replace('_', ' ')} improved from {r_pre:.1%} to {r_post:.1%} ({rel:.0%} better) but is still above the recovery band of {band:.1%}; the root cause may be only partly addressed."
        if days_post >= 6:
            verdict = "not_recovered"
            expl += f" After {days_post} days the KPI has not returned to the recovery band, so the intervention is judged insufficient."
    else:
        verdict = "not_recovered"
        expl = f"{issue.kpi_name.replace('_', ' ')} is {r_post:.1%} after the intervention versus {r_pre:.1%} before ({rel:+.0%} change, p={p_improve:.2f}); no significant improvement - the hypothesis behind this action is not supported."
    res.update(verdict=verdict, explanation=expl)
    # context: did units outside the targeted scope move the same way? (guards against attributing a general trend)
    scope = (iv.params or {}).get("scope") or {}
    cols = {k: v for k, v in scope.items() if k in f.columns}
    if cols:
        m = pd.Series(True, index=f.index)
        for k, v in cols.items():
            m &= f[k].isin(v if isinstance(v, list) else [v])
        if m.any() and (~m).any():
            def rate(mask, df):
                d = df[mask.reindex(df.index, fill_value=False)]
                return d["k"].sum() / d["n"].sum() if d["n"].sum() else None
            res["control"] = {"targeted_pre": rate(m, pre), "targeted_post": rate(m, post), "other_pre": rate(~m, pre), "other_post": rate(~m, post)}
    # secondary KPIs
    kp = daily_kpis(view)
    sec = {}
    for code, better in SECONDARY.items():
        if code not in kp:
            continue
        a = kp.loc[(kp.index >= exec_day - pd.Timedelta(days=7)) & (kp.index < exec_day), code].mean()
        b = kp.loc[kp.index >= eff_day, code].mean()
        if pd.notna(a) and pd.notna(b):
            sec[code] = {"pre": float(a), "post": float(b), "improved": bool(b < a if better == "lower" else b > a)}
    res["secondary_kpis"] = sec
    # persist daily measurements for the monitoring charts
    kmap = ensure_kpis(ctx.db)
    code = PRIMARY_KPI.get(issue.kpi_name)
    ctx.db.execute(delete(RecoveryMeasurement).where(RecoveryMeasurement.intervention_id == iv.id))
    if code:
        d = pd.concat([pre.assign(phase="pre"), post.assign(phase="post")]).groupby(["date", "phase"])[["n", "k"]].sum().reset_index()
        for r in d.itertuples():
            ctx.db.add(RecoveryMeasurement(kpi_id=kmap[code].id, issue_id=issue.id, intervention_id=iv.id, measured_on=r.date.date(), value=100 * (1 - r.k / r.n),
                                           numerator=float(r.n - r.k), denominator=float(r.n), phase=r.phase, is_simulated=True))
    return res


def run(ctx: Ctx, issue_id: int) -> AgentResult:
    db = ctx.db
    issue = db.get(DetectedIssue, issue_id)
    ivs = list(db.scalars(select(Intervention).where(Intervention.issue_id == issue_id, Intervention.status == "executed", Intervention.role == "root_cause_fix",
                                                     Intervention.verification_status.in_(["monitoring", "partial", "insufficient_data", "not_started"]))))
    if not ivs or not issue.kpi_name:
        return AgentResult(output={"results": []}, reasoning="No executed root-cause interventions are awaiting verification.")
    results = [_verify_one(ctx, issue, iv) for iv in ivs]
    inv = get_investigation(db, issue_id)
    reopen = False
    for iv, r in zip(ivs, results):
        verdict = r["verdict"]
        iv.verification_status = "monitoring" if verdict == "insufficient_data" else verdict
        if verdict in ("recovered", "not_recovered"):
            iv.verified_at = utcnow()
    verdicts = {r["verdict"] for r in results}
    if "recovered" in verdicts:
        issue.status, inv.status, inv.stage = "resolved", "resolved", "verified"
        notify(db, f"Recovery verified: {issue.code}", results[0]["explanation"], "success", "/monitoring")
    elif "not_recovered" in verdicts:
        issue.status, inv.status, inv.stage = "reopened", "reopened", "reinvestigating"
        issue.reopen_count += 1
        issue.iteration += 1
        inv.iteration = issue.iteration
        reopen = True
        ctx.flags["reopen"] = True
        notify(db, f"Intervention failed - investigation reopened: {issue.code}", next(r["explanation"] for r in results if r["verdict"] == "not_recovered"), "error", f"/investigations/{issue.id}")
    else:
        issue.status = "monitoring"
        inv.status, inv.stage = "monitoring", "monitoring"
    db.flush()
    summary = "; ".join(f"{r['intervention']}: {r['verdict']}" for r in results)
    return AgentResult(output={"results": results, "reopened": reopen}, reasoning=" ".join(r["explanation"] for r in results) + (" Investigation re-opened." if reopen else ""),
                       inputs={"issue": issue.code, "interventions": summary})
