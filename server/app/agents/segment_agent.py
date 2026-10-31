"""Agent 3 - Customer Segmentation.

Finds which customer groups are over-represented among affected customers (Fisher exact test, Benjamini-Hochberg corrected),
with privacy and fairness guard-rails: only an allow-list of behavioural / commercial attributes is used (never protected
attributes), groups smaller than ``min_group_size`` are suppressed (k-anonymity) and no customer identifiers are emitted.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.agents.common import save_inv_state
from app.agents.context import AgentResult, Ctx
from app.analytics import stats
from app.analytics.frames import KPI_BY_ASPECT
from app.models import DetectedIssue

PROTECTED_ATTRIBUTES = {"gender", "age", "religion", "ethnicity", "caste", "disability", "nationality", "marital_status", "pincode"}
STATIC_DIMS = ["city", "plan", "segment_code", "tenure_band", "ltv_band", "platform", "os_version", "complaint_freq_band", "order_freq_band"]
ORDER_DIMS = ["delivery_partner", "payment_method", "gateway", "app_version", "category", "supplier", "batch", "refund_type", "warehouse"]
DIM_LABEL = {"city": "City", "plan": "Subscription plan", "segment_code": "Customer segment", "tenure_band": "Tenure", "ltv_band": "Lifetime value",
             "platform": "Platform", "os_version": "OS version", "complaint_freq_band": "Prior complaint frequency", "order_freq_band": "Order frequency",
             "delivery_partner": "Delivery partner", "payment_method": "Payment method", "gateway": "Payment gateway", "app_version": "App version",
             "category": "Product category", "supplier": "Supplier", "batch": "Product batch", "refund_type": "Refund type", "warehouse": "Warehouse"}
assert not (set(STATIC_DIMS) | set(ORDER_DIMS)) & PROTECTED_ATTRIBUTES


def _sev(rate: float, lift: float) -> str:
    if rate >= 0.4 and lift >= 2:
        return "critical"
    if rate >= 0.25 and lift >= 2:
        return "high"
    if rate >= 0.12 and lift >= 1.5:
        return "medium"
    return "low"


def _bands(cust: pd.DataFrame, voice: pd.DataFrame, tx: pd.DataFrame, onset: pd.Timestamp) -> pd.DataFrame:
    c = cust.copy()
    c["tenure_band"] = pd.cut(c["tenure_days"], [-1, 89, 364, 729, 10**6], labels=["<90d", "90d-1y", "1-2y", "2y+"]).astype(str)
    q = c["lifetime_value"].quantile([1 / 3, 2 / 3]).tolist()
    c["ltv_band"] = np.select([c["lifetime_value"] <= q[0], c["lifetime_value"] <= q[1]], ["low", "mid"], "high")
    prior = voice[voice["negative"] & (voice["date"] < onset)].groupby("customer_id").size() if not voice.empty else pd.Series(dtype=int)
    n = c["customer_id"].map(prior).fillna(0)
    c["complaint_freq_band"] = np.select([n == 0, n == 1], ["none", "once"], "2+")
    if not tx.empty:
        orders = tx[tx["order_at"] < onset].groupby("customer_id").size()
        m = c["customer_id"].map(orders).fillna(0)
        c["order_freq_band"] = np.select([m == 0, m <= 2], ["new/none", "1-2"], "3+")
    else:
        c["order_freq_band"] = "n/a"
    return c


def run(ctx: Ctx, issue_id: int) -> AgentResult:
    db, k_min = ctx.db, ctx.s.min_group_size
    issue = db.get(DetectedIssue, issue_id)
    onset = pd.Timestamp(issue.onset_at).normalize() if issue.onset_at else pd.Timestamp(ctx.view.w.recent_start)
    v, tx, cust = ctx.view.voice(), ctx.view.tx(), ctx.view.customers()
    kpi = KPI_BY_ASPECT.get(issue.aspect)
    A: set[int] = set()
    if not v.empty:
        vv = v[v["negative"] & ~v["is_flagged"] & (v["primary_aspect"] == issue.aspect) & (v["date"] >= onset - pd.Timedelta(days=2))]
        A |= set(vv["customer_id"].dropna().astype(int))
    bad_rows = pd.DataFrame()
    if kpi:
        f = ctx.view.kpi_frame(kpi[0])
        bad_rows = f[(f["k"] > 0) & (f["date"] >= onset)]
        A |= set(bad_rows["customer_id"].dropna().astype(int))
    recent_tx = tx[tx["order_at"] >= pd.Timestamp(ctx.now) - pd.Timedelta(days=21)] if not tx.empty else tx
    active = set(recent_tx["customer_id"].dropna().astype(int)) | A if not tx.empty else A
    c = _bands(cust, v, tx, onset)
    U = c[c["customer_id"].isin(active)].copy()
    U["affected"] = U["customer_id"].isin(A)
    N, A_tot = len(U), int(U["affected"].sum())
    if N == 0 or A_tot == 0:
        res = {"affected_customers": 0, "active_customers": N, "segments": [], "predefined": [], "geography": []}
        save_inv_state(db, issue_id, "segmentation", res)
        return AgentResult(output=res, reasoning="No affected customers could be linked to the issue evidence.")
    overall = A_tot / N

    tests, suppressed = [], 0
    post_tx = tx[(tx["order_at"] >= onset) & tx["customer_id"].notna()] if not tx.empty else tx
    for dim in STATIC_DIMS:
        if dim not in U.columns:
            continue
        for val, g in U.groupby(dim):
            tests.append((dim, str(val), set(g["customer_id"])))
    for dim in ORDER_DIMS:
        if post_tx.empty or dim not in post_tx.columns:
            continue
        for val, g in post_tx.groupby(dim):
            if val in ("", None) or (isinstance(val, float) and np.isnan(val)):
                continue
            tests.append((dim, str(val), set(g["customer_id"].astype(int)) & set(U["customer_id"])))
    rows = []
    for dim, val, members in tests:
        n_v = len(members)
        a_v = len(members & A)
        if n_v < k_min:
            suppressed += 1
            continue
        rate = a_v / n_v
        rows.append({"dimension": dim, "label": DIM_LABEL.get(dim, dim), "value": val, "customers": n_v, "affected": a_v, "rate": rate,
                     "lift": rate / overall if overall else 0.0, "p": stats.fisher_greater(a_v, n_v, A_tot, N)})
    adj = stats.benjamini_hochberg([r["p"] for r in rows])
    for r, a in zip(rows, adj):
        r["p_adj"] = a
        r["share_of_affected"] = r["affected"] / A_tot
        r["severity"] = _sev(r["rate"], r["lift"])
    sig = [r for r in rows if r["affected"] >= 5 and r["lift"] >= 1.3 and r["p_adj"] < 0.01]
    sig.sort(key=lambda r: -(r["lift"] * np.log1p(r["affected"])))
    for r in sig:
        r["pattern"] = f"{r['label']} = {r['value']}: {r['rate']:.0%} of customers affected vs {overall:.0%} overall ({r['lift']:.1f}x, {r['affected']} of {r['customers']})"

    spend = (tx[(tx["order_at"] >= pd.Timestamp(ctx.now) - pd.Timedelta(days=30)) & (tx["payment_status"] != "failed")].groupby("customer_id")["amount"].sum()
             if not tx.empty else pd.Series(dtype=float))
    U["spend_30d"] = U["customer_id"].map(spend).fillna(0.0)

    def table(col):
        out = []
        for val, g in U.groupby(col):
            n_v, a_v = len(g), int(g["affected"].sum())
            if n_v < k_min:
                continue
            out.append({"value": str(val), "customers": n_v, "affected": a_v, "rate": a_v / n_v, "lift": (a_v / n_v) / overall,
                        "revenue_exposure_30d": float(g.loc[g["affected"], "spend_30d"].sum()), "avg_ltv": float(g["lifetime_value"].mean()),
                        "severity": _sev(a_v / n_v, (a_v / n_v) / overall)})
        return sorted(out, key=lambda r: -r["rate"])

    predefined = table("segment_code")
    names = {}
    from app.models import CustomerSegment
    for s in db.query(CustomerSegment):
        names[s.code] = s.name
    for r in predefined:
        r["name"] = names.get(r["value"], r["value"])
    geography = table("city")
    products = []
    if not bad_rows.empty and "category" in bad_rows.columns:
        pc = bad_rows.groupby("category")["k"].sum().sort_values(ascending=False)
        products = [{"value": str(i), "bad_events": int(x)} for i, x in pc.items()]
    res = {"affected_customers": A_tot, "active_customers": N, "affected_rate": overall, "segments": sig[:12], "predefined": predefined, "geography": geography,
           "products": products, "suppressed_groups": suppressed, "k_anonymity_min_group": k_min, "tests_run": len(rows),
           "privacy_notes": [f"Groups with fewer than {k_min} customers are suppressed (k-anonymity).", "No customer identifiers are emitted; analysis uses pseudonymous IDs only.",
                             "Only behavioural, commercial and location attributes are used; protected attributes are excluded by design.",
                             "Targeting for remediation is based on the experienced failure, not on segment membership, to avoid unequal treatment."],
           "revenue_exposure_30d": float(U.loc[U["affected"], "spend_30d"].sum())}
    save_inv_state(db, issue_id, "segmentation", res)
    top = ", ".join(f"{s['label']}={s['value']}" for s in sig[:3]) or "no over-represented group"
    return AgentResult(output={k: v for k, v in res.items() if k not in ("predefined", "geography", "products", "privacy_notes")} | {"segment_count": len(sig)},
                       reasoning=f"{A_tot} of {N} active customers are affected ({overall:.1%}). Over-represented groups (Fisher exact, BH-adjusted p<0.01): {top}. "
                                 f"{suppressed} groups below k={k_min} were suppressed for privacy.",
                       inputs={"issue": issue.code, "onset": str(onset.date())})
