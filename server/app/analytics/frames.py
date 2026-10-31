"""DataFrame views over the signal store. Every agent analyses these frames, never raw ground truth."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import Customer, CustomerSignal, OperationalEvent, ProductRelease
from app.services import nlp

KPI_BY_ASPECT = {
    "delivery": ("late_delivery_rate", "Late delivery rate"),
    "payment": ("payment_failure_rate", "Payment failure rate"),
    "app": ("crash_rate", "Session crash rate"),
    "product_quality": ("defect_return_rate", "Defective return rate"),
    "refund": ("refund_sla_breach_rate", "Refund SLA breach rate"),
}
KPI_DIMS = {
    "late_delivery_rate": ["city", "delivery_partner", "warehouse", "category", "plan"],
    "payment_failure_rate": ["payment_method", "gateway", "app_version", "platform", "os_version", "city"],
    "crash_rate": ["app_version", "platform", "os_version"],
    "defect_return_rate": ["sku", "supplier", "batch", "category", "city"],
    "refund_sla_breach_rate": ["refund_type", "city", "payment_method", "category"],
}
DEFECT_CENSOR_DAYS = 5


@dataclass
class Windows:
    data_start: datetime
    baseline_end: datetime
    recent_start: datetime
    now: datetime

    @property
    def baseline_days(self) -> int:
        return max(1, (self.baseline_end - self.data_start).days)

    @property
    def recent_days(self) -> int:
        return max(1, (self.now - self.recent_start).days)


def day_floor(dt) -> pd.Timestamp:
    return pd.Timestamp(dt).normalize()


def compute_windows(db: Session, now: datetime, s: Settings) -> Windows:
    first = db.scalar(select(CustomerSignal.occurred_at).where(CustomerSignal.is_current.is_(True)).order_by(CustomerSignal.occurred_at).limit(1))
    start = day_floor(first).to_pydatetime() if first else now - timedelta(days=30)
    base_end = min(start + timedelta(days=s.baseline_days), now - timedelta(days=s.recent_days))
    return Windows(start, base_end, now - timedelta(days=s.recent_days), now)


class DataView:
    """Lazy, cached frames for one analysis run (keeps agents independent of SQL)."""

    def __init__(self, db: Session, now: datetime, settings: Settings, knowledge_time: datetime | None = None):
        """``now`` is the simulated analysis clock; ``knowledge_time`` (wall clock) replays the store as it was known at that moment."""
        self.db, self.now, self.s, self.kt = db, now, settings, knowledge_time
        self.w = compute_windows(db, now, settings)
        self._c: dict = {}

    def _cache(self, key, fn):
        if key not in self._c:
            self._c[key] = fn()
        return self._c[key]

    def customers(self) -> pd.DataFrame:
        def load():
            rows = self.db.execute(select(Customer.id, Customer.customer_ref, Customer.city, Customer.plan, Customer.tenure_days,
                                          Customer.lifetime_value, Customer.platform, Customer.os_version, Customer.complaints_90d,
                                          Customer.orders_90d, Customer.segment_id)).all()
            df = pd.DataFrame(rows, columns=["customer_id", "customer_ref", "city", "plan", "tenure_days", "lifetime_value", "platform",
                                             "os_version", "complaints_90d", "orders_90d", "segment_id"])
            from app.models import CustomerSegment

            seg = {s.id: s.code for s in self.db.scalars(select(CustomerSegment))}
            df["segment_code"] = df["segment_id"].map(seg)
            return df
        return self._cache("customers", load)

    def _signals(self, types: list[str]) -> pd.DataFrame:
        q = select(CustomerSignal.id, CustomerSignal.external_id, CustomerSignal.source_type, CustomerSignal.customer_id,
                   CustomerSignal.occurred_at, CustomerSignal.text, CustomerSignal.numeric_value, CustomerSignal.metric_name,
                   CustomerSignal.sentiment, CustomerSignal.primary_aspect, CustomerSignal.attributes, CustomerSignal.segment,
                   CustomerSignal.region, CustomerSignal.reliability, CustomerSignal.is_flagged, CustomerSignal.is_injected,
                   CustomerSignal.product, CustomerSignal.revision).where(CustomerSignal.source_type.in_(types), CustomerSignal.occurred_at <= self.now)
        q = q.where(CustomerSignal.ingested_at <= self.kt) if self.kt is not None else q.where(CustomerSignal.is_current.is_(True))
        df = pd.DataFrame(self.db.execute(q).all())
        if df.empty:
            return pd.DataFrame(columns=["id", "external_id", "source_type", "customer_id", "occurred_at", "text", "numeric_value",
                                         "metric_name", "sentiment", "primary_aspect", "attributes", "segment", "region",
                                         "reliability", "is_flagged", "is_injected", "product", "revision"])
        if self.kt is not None:  # point-in-time replay: the latest revision known at that moment wins
            df = df.sort_values(["source_type", "external_id", "revision"]).drop_duplicates(["source_type", "external_id"], keep="last")
        df["occurred_at"] = pd.to_datetime(df["occurred_at"])
        return df.reset_index(drop=True)

    def voice(self) -> pd.DataFrame:
        """Customer-voice signals with a `negative` flag. Prompt-injection-flagged rows are excluded from analytics."""
        def load():
            df = self._signals(["review", "ticket", "social", "survey"])
            if df.empty:
                df["negative"] = []
                return df
            cat = df["attributes"].map(lambda a: (a or {}).get("category"))
            df["category"] = cat
            df["negative"] = [nlp.is_negative_voice(st, num if st in ("review", "survey") else None, sent, c)
                              for st, num, sent, c in zip(df["source_type"], df["numeric_value"], df["sentiment"], cat)]
            df["date"] = df["occurred_at"].dt.normalize()
            return df
        return self._cache("voice", load)

    def tx(self) -> pd.DataFrame:
        def load():
            df = self._signals(["transaction"])
            if df.empty:
                return df
            a = pd.json_normalize(df["attributes"].map(lambda x: x or {}).tolist())
            df = pd.concat([df.drop(columns=["attributes"]).reset_index(drop=True), a.reset_index(drop=True)], axis=1)
            df = df.rename(columns={"id": "signal_id", "external_id": "order_id", "numeric_value": "amount", "occurred_at": "order_at"})
            for c in ("promised_at", "delivered_at", "refund_requested_at", "refund_completed_at"):
                df[c] = pd.to_datetime(df.get(c), errors="coerce")
            df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
            df["recovered_by_retry"] = pd.to_numeric(df.get("recovered_by_retry"), errors="coerce").fillna(0).astype(int)
            for c in ("gateway", "failure_code", "os_version", "refund_type", "return_reason", "batch"):
                if c in df:
                    df[c] = df[c].fillna("")
            cu = self.customers()[["customer_id", "plan", "segment_code", "tenure_days", "lifetime_value"]]
            return df.merge(cu, on="customer_id", how="left")
        return self._cache("tx", load)

    def telemetry(self) -> pd.DataFrame:
        def load():
            df = self._signals(["telemetry"])
            if df.empty:
                return df
            a = pd.json_normalize(df["attributes"].tolist())
            df = pd.concat([df[["id", "occurred_at"]].reset_index(drop=True), a], axis=1).rename(columns={"id": "signal_id"})
            df["date"] = df["occurred_at"].dt.normalize()
            df["os_version"] = df["os_version"].fillna("")
            return df
        return self._cache("tel", load)

    def metrics(self) -> pd.DataFrame:
        def load():
            df = self._signals(["operational_metric"])
            if df.empty:
                return pd.DataFrame(columns=["signal_id", "date", "metric_name", "entity", "entity_type", "value"])
            a = pd.json_normalize(df["attributes"].tolist())
            out = pd.concat([df[["id", "occurred_at", "metric_name", "numeric_value", "reliability"]].reset_index(drop=True), a], axis=1)
            out = out.rename(columns={"id": "signal_id", "numeric_value": "value"})
            out["date"] = out["occurred_at"].dt.normalize()
            return out
        return self._cache("met", load)

    def events(self) -> list[OperationalEvent]:
        return self._cache("events", lambda: list(self.db.scalars(select(OperationalEvent).where(OperationalEvent.start_at <= self.now).order_by(OperationalEvent.start_at))))

    def releases(self) -> list[ProductRelease]:
        return self._cache("rel", lambda: list(self.db.scalars(select(ProductRelease).where(ProductRelease.deployed_at <= self.now).order_by(ProductRelease.deployed_at))))

    # ---- KPI frames ------------------------------------------------------------------------------------
    def kpi_frame(self, kpi: str) -> pd.DataFrame:
        """Rows of (date, n, k, dims...) for a structured KPI. `date` is the cohort (initiation) date."""
        return self._cache(("kpi", kpi), lambda: self._build_kpi_frame(kpi))

    def _build_kpi_frame(self, kpi: str) -> pd.DataFrame:
        now, sla = self.now, self.s.refund_sla_hours
        if kpi == "crash_rate":
            t = self.telemetry()
            if t.empty:
                return pd.DataFrame(columns=["date", "n", "k"])
            f = t.rename(columns={"sessions": "n", "crashes": "k"})
            return f[["signal_id", "date", "n", "k"] + KPI_DIMS[kpi]].assign(customer_id=np.nan)
        tx = self.tx()
        if tx.empty:
            return pd.DataFrame(columns=["date", "n", "k"])
        if kpi == "payment_failure_rate":
            f = tx.copy()
            f["k"] = (f["payment_status"] == "failed").astype(int)
        elif kpi == "late_delivery_rate":
            f = tx[(tx["payment_status"] != "failed") & (tx["delivery_status"] != "cancelled") & tx["promised_at"].notna() & (tx["promised_at"] <= now)].copy()
            f["k"] = (f["delivered_at"].isna() | (f["delivered_at"] > f["promised_at"])).astype(int)
        elif kpi == "defect_return_rate":
            cut = now - timedelta(days=DEFECT_CENSOR_DAYS)
            f = tx[tx["delivered_at"].notna() & (tx["delivered_at"] <= cut)].copy()
            f["k"] = (f["return_reason"] == "defective").astype(int)
        elif kpi == "refund_sla_breach_rate":
            f = tx[tx["refund_requested_at"].notna() & (tx["refund_requested_at"] + pd.Timedelta(hours=sla) <= now)].copy()
            done = f["refund_completed_at"]
            f["k"] = (done.isna() | ((done - f["refund_requested_at"]) > pd.Timedelta(hours=sla))).astype(int)
            f["order_at"] = f["refund_requested_at"]
        else:
            raise KeyError(kpi)
        f["n"] = 1
        f["date"] = f["order_at"].dt.normalize()
        f["ts"] = f["order_at"]
        cols = ["signal_id", "customer_id", "date", "ts", "n", "k", "order_id", "amount"] + KPI_DIMS[kpi]
        return f[[c for c in cols if c in f.columns]].reset_index(drop=True)

    def daily_rate(self, kpi: str, where: pd.Series | None = None) -> pd.DataFrame:
        f = self.kpi_frame(kpi)
        if where is not None:
            f = f[where.reindex(f.index, fill_value=False)]
        if f.empty:
            return pd.DataFrame(columns=["date", "n", "k", "rate"])
        d = f.groupby("date")[["n", "k"]].sum().reset_index()
        d["rate"] = d["k"] / d["n"].where(d["n"] > 0, np.nan)
        return d

    def period_split(self, f: pd.DataFrame, onset) -> tuple[pd.DataFrame, pd.DataFrame]:
        onset = pd.Timestamp(onset)
        base_end = pd.Timestamp(self.w.baseline_end)
        pre = f[f["date"] < min(onset, base_end)] if f is not None else f
        post = f[f["date"] >= onset]
        return pre, post
