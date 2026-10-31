"""Daily business KPIs derived from ingested signals (used for the 30-day history and recovery monitoring)."""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analytics.frames import DataView
from app.models import RecoveryKpi, RecoveryMeasurement

KPI_DEFS = [
    ("complaint_volume", "Complaint volume", "count/day", "lower_better", None, "Negative customer-voice signals per day"),
    ("csat", "Customer satisfaction", "1-5", "higher_better", 4.0, "Mean review rating and survey CSAT"),
    ("resolution_time_hours", "Ticket resolution time", "hours", "lower_better", 24.0, "Mean hours to resolve support tickets"),
    ("delivery_success_rate", "Delivery success rate", "%", "higher_better", 92.0, "Orders delivered by the promised time"),
    ("payment_success_rate", "Payment success rate", "%", "higher_better", 97.0, "Payment attempts that succeeded"),
    ("refund_completion_rate", "Refund completion within SLA", "%", "higher_better", 95.0, "Refunds completed inside the SLA"),
    ("service_availability", "Crash-free sessions", "%", "higher_better", 99.5, "Share of app sessions without a crash"),
    ("repeat_complaint_rate", "Repeat complaint rate", "%", "lower_better", None, "Complaining customers who also complained in the prior 14 days"),
    ("customer_retention", "Weekly repeat-purchase retention", "%", "higher_better", None, "Customers active last week who ordered again this week"),
]


def ensure_kpis(db: Session) -> dict[str, RecoveryKpi]:
    have = {k.code: k for k in db.scalars(select(RecoveryKpi))}
    for code, name, unit, direction, target, desc in KPI_DEFS:
        if code not in have:
            k = RecoveryKpi(code=code, name=name, unit=unit, direction=direction, target=target, description=desc)
            db.add(k)
            have[code] = k
    db.flush()
    return have


def daily_kpis(view: DataView) -> pd.DataFrame:
    """One row per day, columns = KPI codes, plus numerator/denominator frames as attrs for transparency."""
    w = view.w
    days = pd.date_range(pd.Timestamp(w.data_start).normalize(), pd.Timestamp(view.now).normalize() - pd.Timedelta(days=1))
    out = pd.DataFrame(index=days, columns=[k[0] for k in KPI_DEFS], dtype=float)
    parts: dict[str, pd.DataFrame] = {}

    v = view.voice()
    if not v.empty:
        neg = v[v["negative"] & ~v["is_flagged"]]
        out["complaint_volume"] = neg.groupby("date").size().reindex(days).fillna(0)
        sc = v[v["source_type"].isin(["review", "survey"]) & v["numeric_value"].notna() & v["metric_name"].isin(["rating", "csat"])]
        g = sc.groupby("date")["numeric_value"].agg(["sum", "count"]).reindex(days)
        out["csat"] = g["sum"] / g["count"]
        parts["csat"] = g.rename(columns={"sum": "num", "count": "den"})
        tk = v[(v["source_type"] == "ticket") & v["numeric_value"].notna() & (v["metric_name"] == "resolution_hours")]
        out["resolution_time_hours"] = tk.groupby("date")["numeric_value"].mean().reindex(days)
        c = neg[neg["customer_id"].notna()][["date", "customer_id"]].drop_duplicates()
        rates = []
        for d in days:
            today = set(c.loc[c["date"] == d, "customer_id"])
            prior = set(c.loc[(c["date"] < d) & (c["date"] >= d - pd.Timedelta(days=14)), "customer_id"])
            rates.append(len(today & prior) / len(today) * 100 if today else np.nan)
        out["repeat_complaint_rate"] = rates

    for kpi, col, inverse in (("late_delivery_rate", "delivery_success_rate", True), ("payment_failure_rate", "payment_success_rate", True),
                              ("refund_sla_breach_rate", "refund_completion_rate", True)):
        d = view.daily_rate(kpi)
        if not d.empty:
            s = d.set_index("date")
            out[col] = ((1 - s["k"] / s["n"]) * 100).reindex(days)
            parts[col] = pd.DataFrame({"num": (s["n"] - s["k"]).reindex(days), "den": s["n"].reindex(days)})
    t = view.daily_rate("crash_rate")
    if not t.empty:
        s = t.set_index("date")
        out["service_availability"] = ((1 - s["k"] / s["n"]) * 100).reindex(days)
        parts["service_availability"] = pd.DataFrame({"num": (s["n"] - s["k"]).reindex(days), "den": s["n"].reindex(days)})

    tx = view.tx()
    if not tx.empty:
        t2 = tx[tx["payment_status"] != "failed"][["order_at", "customer_id"]].dropna()
        t2["date"] = t2["order_at"].dt.normalize()
        by_day = t2.groupby("date")["customer_id"].agg(set)
        ret = []
        for d in days:
            last = set().union(*[by_day.get(d - pd.Timedelta(days=i), set()) for i in range(0, 7)])
            prev = set().union(*[by_day.get(d - pd.Timedelta(days=i), set()) for i in range(7, 14)])
            ret.append(len(last & prev) / len(prev) * 100 if len(prev) >= 50 else np.nan)
        out["customer_retention"] = ret
    out.attrs["parts"] = parts
    return out


def persist_history(db: Session, view: DataView) -> int:
    kpis = ensure_kpis(db)
    df = daily_kpis(view)
    db.execute(delete(RecoveryMeasurement).where(RecoveryMeasurement.issue_id.is_(None), RecoveryMeasurement.intervention_id.is_(None)))
    parts = df.attrs.get("parts", {})
    rows = []
    for code in df.columns:
        for d, val in df[code].items():
            if pd.isna(val):
                continue
            p = parts.get(code)
            num = den = None
            if p is not None and d in p.index and not pd.isna(p.loc[d, "den"]):
                num, den = float(p.loc[d, "num"]), float(p.loc[d, "den"])
            rows.append({"kpi_id": kpis[code].id, "measured_on": d.date(), "value": float(val), "numerator": num, "denominator": den,
                         "phase": "history", "is_simulated": True})
    if rows:
        db.bulk_insert_mappings(RecoveryMeasurement, rows)
    db.flush()
    return len(rows)
