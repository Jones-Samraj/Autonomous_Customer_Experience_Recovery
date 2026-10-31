"""Agent 5 - Business Impact Assessment. Every number is labelled measured or estimated, with formula, inputs, assumptions and range."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from sqlalchemy import select, update

from app.agents.common import inv_state
from app.agents.context import AgentResult, Ctx
from app.agents.domain import CHURN_BETA
from app.agents.issue_agent import severity_label
from app.analytics import stats
from app.analytics.frames import KPI_BY_ASPECT
from app.db import utcnow
from app.models import BusinessImpactEstimate, DetectedIssue

COST_PER_TICKET_INR = 180.0
HANDLING_COST_PER_EVENT_INR = 60.0
HORIZON_MONTHS = 3
BASE_CHURN = 0.05


def current_estimates(db, issue_id: int) -> dict[str, BusinessImpactEstimate]:
    return {e.metric: e for e in db.scalars(select(BusinessImpactEstimate).where(BusinessImpactEstimate.issue_id == issue_id, BusinessImpactEstimate.is_current.is_(True)))}


def run(ctx: Ctx, issue_id: int) -> AgentResult:
    db = ctx.db
    issue = db.get(DetectedIssue, issue_id)
    seg = inv_state(db, issue_id).get("segmentation") or {}
    kpi_code, kpi_label = KPI_BY_ASPECT.get(issue.aspect, (None, None))
    onset = pd.Timestamp(issue.onset_at).normalize() if issue.onset_at else pd.Timestamp(ctx.view.w.recent_start)
    tx, v = ctx.view.tx(), ctx.view.voice()
    now = pd.Timestamp(ctx.now)
    monthly_rev = float(tx[(tx["order_at"] >= now - pd.Timedelta(days=30)) & (tx["payment_status"] != "failed")]["amount"].sum()) if not tx.empty else 0.0
    measured = int(seg.get("affected_customers", 0))
    active = int(seg.get("active_customers", 0))
    f = ctx.view.kpi_frame(kpi_code) if kpi_code else pd.DataFrame()
    bad = f[(f["k"] > 0) & (f["date"] >= onset)] if not f.empty else f
    out: list[dict] = []

    def est(metric, label, value, unit, kind, formula, inputs, assumptions, lo=None, hi=None):
        out.append({"metric": metric, "label": label, "value": None if value is None else float(value), "unit": unit, "kind": kind, "formula": formula,
                    "inputs": inputs, "assumptions": assumptions, "ci_low": lo, "ci_high": hi})

    est("affected_customers_measured", "Affected customers (measured)", measured, "customers", "measured",
        "|distinct customers with a linked complaint, or a late / failed / defective / breached record, since onset|",
        {"affected": measured, "active_customers": active, "onset": str(onset.date())}, ["Customers are pseudonymous IDs; duplicates are counted once."])

    # customers newly affected per day over the last 3 known days -> 7-day exposure if unresolved
    last = f["date"].max() if not f.empty else now - pd.Timedelta(days=1)
    recent_ids = set()
    if not bad.empty:
        recent_ids |= set(bad[bad["date"] > last - pd.Timedelta(days=3)]["customer_id"].dropna().astype(int))
    if not v.empty:
        vv = v[v["negative"] & ~v["is_flagged"] & (v["primary_aspect"] == issue.aspect) & (v["date"] > last - pd.Timedelta(days=3))]
        recent_ids |= set(vv["customer_id"].dropna().astype(int))
    per_day = len(recent_ids) / 3
    next7 = per_day * 7
    half = 1.96 * math.sqrt(max(len(recent_ids), 1)) / 3 * 7
    est("affected_customers_next_7d", "Additional customers affected in the next 7 days if unresolved", next7, "customers", "estimated",
        "newly affected customers per day (last 3 known days) x 7", {"new_customers_last_3_days": len(recent_ids), "per_day": per_day},
        ["Current inflow continues unchanged for 7 days.", "Poisson sampling uncertainty (95%)."], max(0.0, next7 - half), next7 + half)
    total_est = measured + next7
    lo_cust, hi_cust = measured + max(0.0, next7 - half), measured + next7 + half

    spend_total = float(seg.get("revenue_exposure_30d", 0.0))
    spend = spend_total / measured if measured else (monthly_rev / max(active, 1))
    rep = 0.0
    if measured and not bad.empty:
        per_cust = bad.groupby("customer_id").size()
        rep = float((per_cust >= 2).mean()) if len(per_cust) else 0.0
    beta = CHURN_BETA.get(issue.aspect, 0.1)
    uplift = beta * (1 + 0.5 * rep)
    rar = total_est * spend * uplift * HORIZON_MONTHS
    est("revenue_at_risk", f"Revenue at risk ({HORIZON_MONTHS}-month horizon)", rar, "INR", "estimated",
        "revenue_at_risk = affected_customers x avg_monthly_spend x churn_uplift x horizon_months;  churn_uplift = beta_issue x (1 + 0.5 x repeat_share)",
        {"affected_customers_total": round(total_est, 1), "avg_monthly_spend_inr": round(spend, 2), "beta_issue": beta, "repeat_share": round(rep, 3),
         "churn_uplift": round(uplift, 4), "horizon_months": HORIZON_MONTHS},
        [f"beta_issue={beta} is an assumed churn uplift for this issue category (configurable domain prior).", "Spend is the last-30-day order value of affected customers.",
         "Range uses beta x 0.6 to x 1.4 and the 95% interval of affected customers."], lo_cust * spend * uplift * 0.6 * HORIZON_MONTHS, hi_cust * spend * uplift * 1.4 * HORIZON_MONTHS)

    direct = None
    if not tx.empty and kpi_code:
        post = tx[tx["order_at"] >= onset]
        if issue.aspect == "payment":
            lost = post[(post["payment_status"] == "failed") & (post["recovered_by_retry"] == 0)]
            direct = ("Order value lost to failed payments", float(lost["amount"].sum()), "sum(order value of failed payment attempts that were not recovered by retry)", {"failed_unrecovered": int(len(lost))})
        elif issue.aspect == "product_quality":
            d = post[post["return_reason"] == "defective"]
            direct = ("Refund liability on defective returns", float(pd.to_numeric(d.get("refund_amount"), errors="coerce").fillna(d["amount"]).sum()), "sum(refund amount of defective returns since onset)", {"returns": int(len(d))})
        elif issue.aspect == "refund" and not bad.empty:
            direct = ("Refund amount stuck beyond SLA", float(bad["amount"].sum()) if "amount" in bad else 0.0, "sum(refund amount of requests that breached SLA)", {"breached": int(len(bad))})
    if direct:
        est("direct_revenue_impact", direct[0], direct[1], "INR", "measured", direct[2], direct[3], ["Order values as recorded in the transaction system."])

    est("complaint_growth_rate", "Complaint growth vs historical baseline", issue.growth_rate, "ratio", "measured",
        "growth = recent_complaints / expected_from_baseline - 1", {"baseline_daily_mean": (issue.stats or {}).get("text", {}).get("baseline_mean"),
                                                                    "recent_count": (issue.stats or {}).get("text", {}).get("recent_count"),
                                                                    "expected": (issue.stats or {}).get("text", {}).get("expected")}, ["Baseline = first 14 days of history."])
    k = (issue.stats or {}).get("kpi") or {}
    if k:
        lo, hi = stats.wilson(k["k_recent"], k["n_recent"])
        est("service_failure_rate", f"{k['label']} (current)", k["current_rate"], "rate", "measured",
            "failure_rate = failed_or_late_units / total_units (recent window)", {"k": k["k_recent"], "n": k["n_recent"], "baseline_rate": k["baseline_rate"], "z": round(k["z"], 2)},
            ["Wilson 95% interval."], lo, hi)
    risk = min(0.95, BASE_CHURN + uplift)
    est("retention_risk", "Churn probability of affected customers", risk, "probability", "estimated",
        "retention_risk = base_churn + churn_uplift", {"base_churn": BASE_CHURN, "churn_uplift": round(uplift, 4)},
        ["Base churn of 5% over the horizon is an assumption.", "Uplift depends on issue category and repeat exposure."], min(0.95, BASE_CHURN + uplift * 0.6), min(0.95, BASE_CHURN + uplift * 1.4))
    st = (issue.stats or {}).get("text", {})
    extra_tickets = max(0.0, (st.get("recent_count", 0) or 0) - (st.get("expected", 0) or 0))
    bad_events = int(bad["k"].sum()) if not bad.empty else 0
    cost = extra_tickets * COST_PER_TICKET_INR + bad_events * HANDLING_COST_PER_EVENT_INR
    est("operational_cost", "Operational cost impact (support + handling)", cost, "INR", "estimated",
        "cost = extra_tickets x cost_per_ticket + bad_events x handling_cost_per_event",
        {"extra_tickets": round(extra_tickets, 1), "cost_per_ticket_inr": COST_PER_TICKET_INR, "bad_events": bad_events, "handling_cost_inr": HANDLING_COST_PER_EVENT_INR},
        ["Unit costs are assumptions, not measured finance data.", "Range is +/-30%."], cost * 0.7, cost * 1.3)
    ratio = (k.get("current_rate", 0) / k["baseline_rate"]) if k and k.get("baseline_rate") else 1.0
    rar_share = rar / monthly_rev if monthly_rev else 0.0
    comps = {"revenue_at_risk": min(1.0, rar_share / 0.05), "failure_ratio": min(1.0, max(ratio - 1, 0) / 4), "complaint_growth": min(1.0, max(issue.growth_rate or 0, 0) / 2),
             "customer_breadth": min(1.0, (measured / max(active, 1)) / 0.15), "retention_risk": min(1.0, risk / 0.4)}
    w = {"revenue_at_risk": 0.30, "failure_ratio": 0.25, "complaint_growth": 0.20, "customer_breadth": 0.15, "retention_risk": 0.10}
    score = 100 * sum(comps[c] * w[c] for c in comps)
    est("business_severity_score", "Business severity score", score, "0-100", "estimated",
        "score = 100 x sum(weight_i x normalised_component_i)", {"components": {c: round(x, 3) for c, x in comps.items()}, "weights": w, "label": severity_label(score),
                                                                  "monthly_revenue_inr": round(monthly_rev, 0), "revenue_at_risk_share": round(rar_share, 4)},
        ["Normalisation caps: revenue at risk 5% of monthly revenue, failure ratio 5x, growth 200%, breadth 15% of active customers, retention risk 40%."])

    iteration = issue.iteration
    db.execute(update(BusinessImpactEstimate).where(BusinessImpactEstimate.issue_id == issue_id, BusinessImpactEstimate.is_current.is_(True)).values(is_current=False))
    stamp = utcnow()
    for e in out:
        db.add(BusinessImpactEstimate(issue_id=issue_id, iteration=iteration, is_current=True, calculated_at=stamp, **e))
    db.flush()
    summary = {e["metric"]: e["value"] for e in out}
    return AgentResult(output={"summary": summary, "business_severity": severity_label(score)},
                       reasoning=(f"{measured} customers are measurably affected; ~{next7:.0f} more expected within 7 days if unresolved. Revenue at risk is estimated at "
                                  f"INR {rar:,.0f} (range {out[2]['ci_low']:,.0f}-{out[2]['ci_high']:,.0f}) using an assumed churn uplift of {uplift:.1%}; business severity {score:.0f}/100."),
                       inputs={"issue": issue.code, "monthly_revenue_inr": round(monthly_rev, 0)})
