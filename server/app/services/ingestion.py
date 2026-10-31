"""Signal Intelligence ingestion: parse -> validate -> sanitise -> normalise -> persist (with revisions)."""
from __future__ import annotations

import hashlib
import io
import json
import re
import time
from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import (Customer, CustomerSegment, CustomerSignal, DataSource, OperationalEvent, ProductRelease)
from app.services import nlp

MAX_UPLOAD_BYTES = 25 * 1024 * 1024

DATASETS: dict[str, dict] = {
    "customer_reviews": {"label": "Customer reviews", "source_type": "review", "reliability": 0.70,
                         "required": ["review_id", "customer_id", "timestamp", "review_text"], "id": "review_id"},
    "support_tickets": {"label": "Support tickets", "source_type": "ticket", "reliability": 0.90,
                        "required": ["ticket_id", "created_at", "description"], "id": "ticket_id"},
    "social_feedback": {"label": "Social media feedback", "source_type": "social", "reliability": 0.55,
                        "required": ["post_id", "timestamp", "text"], "id": "post_id"},
    "survey_responses": {"label": "Survey responses", "source_type": "survey", "reliability": 0.80,
                         "required": ["response_id", "timestamp", "csat"], "id": "response_id"},
    "transactions": {"label": "Transactions & delivery", "source_type": "transaction", "reliability": 0.98,
                     "required": ["order_id", "customer_id", "order_at", "payment_status"], "id": "order_id"},
    "product_telemetry": {"label": "Product usage telemetry", "source_type": "telemetry", "reliability": 0.95,
                          "required": ["date", "app_version", "platform", "sessions", "crashes"], "id": None},
    "operational_metrics": {"label": "Operational metrics", "source_type": "operational_metric", "reliability": 0.90,
                            "required": ["date", "metric_name", "entity", "value"], "id": None},
    "operational_events": {"label": "Operational events", "source_type": "operational_event", "reliability": 0.85,
                           "required": ["event_id", "event_type", "title", "start_at"], "id": "event_id"},
    "release_history": {"label": "Software release history", "source_type": "release", "reliability": 0.99,
                        "required": ["release_id", "component", "version", "deployed_at"], "id": "release_id"},
    "customers": {"label": "Customer profiles (pseudonymous)", "source_type": "customer", "reliability": 0.95,
                  "required": ["customer_id", "city", "plan"], "id": "customer_id"},
    "customer_segments": {"label": "Customer segments", "source_type": "segment", "reliability": 1.0,
                          "required": ["segment_code", "name"], "id": "segment_code"},
}
SIGNAL_DATASETS = {k for k, v in DATASETS.items() if v["source_type"] in
                   ("review", "ticket", "social", "survey", "transaction", "telemetry", "operational_metric")}
TIME_COLS = {"customer_reviews": ["timestamp"], "support_tickets": ["created_at"], "social_feedback": ["timestamp"],
             "survey_responses": ["timestamp"], "transactions": ["order_at"], "product_telemetry": ["date"],
             "operational_metrics": ["date"], "operational_events": ["start_at"], "release_history": ["deployed_at"]}
WORLD_FRAME_TO_DATASET = {"reviews": "customer_reviews", "tickets": "support_tickets", "social": "social_feedback",
                          "surveys": "survey_responses", "transactions": "transactions", "telemetry": "product_telemetry",
                          "metrics": "operational_metrics", "events": "operational_events", "releases": "release_history"}


def _norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [re.sub(r"\s+", "_", str(c).strip().lower()) for c in df.columns]
    return df


def read_upload(content: bytes, filename: str) -> pd.DataFrame:
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError(f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit")
    name = filename.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(content), dtype=str, keep_default_na=False)
    elif name.endswith((".xlsx", ".xlsm")):
        df = pd.read_excel(io.BytesIO(content), dtype=str, keep_default_na=False, engine="openpyxl")
    else:
        raise ValueError("Unsupported file type. Upload a .csv or .xlsx file")
    return _norm_cols(df)


def detect_dataset_type(columns) -> str | None:
    cols = set(columns)
    best, best_score = None, 0.0
    for k, spec in DATASETS.items():
        req = set(spec["required"])
        score = len(req & cols) / len(req)
        if score == 1.0 and score + len(cols & req) * 0.001 > best_score:
            best, best_score = k, score + len(cols & req) * 0.001
    return best


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.replace("", np.nan), errors="coerce")


def validate(dataset_type: str, df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict], dict]:
    """Return (clean_df, row_errors, summary). Rows that fail validation are rejected, never silently fixed."""
    spec = DATASETS[dataset_type]
    df = _norm_cols(df)
    missing = [c for c in spec["required"] if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns for {spec['label']}: {', '.join(missing)}")
    df = df.reset_index(drop=True)
    df["_row"] = df.index + 2
    errors: list[dict] = []
    bad = pd.Series(False, index=df.index)

    def flag(mask: pd.Series, field: str, msg: str):
        nonlocal bad
        for r in df.loc[mask & ~bad, "_row"].head(10):
            errors.append({"row": int(r), "field": field, "message": msg})
        bad |= mask

    for c in spec["required"]:
        flag(df[c].astype(str).str.strip().eq(""), c, "required value is empty")
    for c in TIME_COLS.get(dataset_type, []):
        parsed = pd.to_datetime(df[c], errors="coerce")
        flag(parsed.isna(), c, "invalid timestamp")
        df[c] = parsed
    rng = {"customer_reviews": [("rating", 1, 5)], "survey_responses": [("csat", 1, 5), ("nps", 0, 10)],
           "transactions": [("amount", 0, None)], "product_telemetry": [("sessions", 0, None), ("crashes", 0, None)],
           "operational_metrics": [("value", None, None)]}
    for col, lo, hi in rng.get(dataset_type, []):
        if col in df.columns:
            v = _num(df[col])
            nonblank = df[col].astype(str).str.strip() != ""
            flag(nonblank & v.isna(), col, "not a number")
            if lo is not None:
                flag(v < lo, col, f"must be >= {lo}")
            if hi is not None:
                flag(v > hi, col, f"must be <= {hi}")
            df[col] = v
    if dataset_type == "product_telemetry":
        flag(_num(df["crashes"]) > _num(df["sessions"]), "crashes", "crashes exceed sessions")
    dup = 0
    idcol = spec["id"]
    if idcol:
        dups = df.duplicated(subset=[idcol], keep="last") & ~bad
        dup = int(dups.sum())
        bad |= dups
    clean = df[~bad].drop(columns=["_row"]).reset_index(drop=True)
    return clean, errors, {"received": int(len(df)), "accepted": int(len(clean)), "rejected": int(bad.sum()),
                           "in_file_duplicates": dup}


def _iso(v):
    if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NaT:
        return None
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.strftime("%Y-%m-%dT%H:%M:%S")
    s = str(v).strip()
    return s or None


def _clean(v):
    if v is None or v is pd.NaT:
        return None
    if isinstance(v, float) and np.isnan(v):
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return None if np.isnan(v) else float(v)
    if isinstance(v, (pd.Timestamp, datetime)):
        return _iso(v)
    if isinstance(v, str):
        return v if v.strip() != "" else None
    return v


def _hash(d: dict) -> str:
    return hashlib.md5(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()


class _Lookup:
    def __init__(self, db: Session):
        self.cust = {c.customer_ref: c for c in db.scalars(select(Customer))}

    def get(self, ref):
        return self.cust.get(str(ref)) if ref else None


def _voice_fields(text: str | None, source_type: str, rating, category=None):
    clean, flagged, reason = nlp.sanitize_untrusted(text)
    sent = nlp.sentiment(clean) if clean else 0.0
    fallback = nlp.TICKET_CATEGORY_TO_ASPECT.get(category or "", None)
    aspect, scores = nlp.primary_aspect(clean, fallback)
    return {"text": clean, "sentiment": round(sent, 4), "primary_aspect": aspect, "aspects": scores,
            "is_flagged": flagged, "flag_reason": reason}


def normalize_row(dataset_type: str, r: dict, lookup: _Lookup) -> dict:
    """Map one validated raw record to the common signal structure."""
    cust = lookup.get(r.get("customer_id"))
    base = {"customer_id": cust.id if cust else None, "segment": cust.segment.code if cust and cust.segment else None,
            "region": (r.get("city") or (cust.city if cust else None)) or None}
    if dataset_type == "customer_reviews":
        out = {**base, "external_id": r["review_id"], "occurred_at": r["timestamp"], "numeric_value": r.get("rating"),
               "metric_name": "rating", "product": r.get("product") or None,
               **_voice_fields(r["review_text"], "review", r.get("rating")),
               "attributes": {"platform": r.get("platform"), "city": r.get("city")}}
    elif dataset_type == "support_tickets":
        res = None
        if r.get("resolved_at") not in (None, ""):
            ra = pd.to_datetime(r["resolved_at"], errors="coerce")
            if pd.notna(ra):
                res = round((ra - r["created_at"]).total_seconds() / 3600, 2)
        out = {**base, "external_id": r["ticket_id"], "occurred_at": r["created_at"], "numeric_value": res,
               "metric_name": "resolution_hours", "product": r.get("product") or None,
               **_voice_fields(r["description"], "ticket", None, r.get("category")),
               "attributes": {k: _clean(r.get(k)) for k in ("category", "priority", "status", "channel", "resolved_at")}
                             | {"resolution_hours": res}}
    elif dataset_type == "social_feedback":
        out = {**base, "external_id": r["post_id"], "occurred_at": r["timestamp"], "numeric_value": None, "metric_name": None,
               "product": None, **_voice_fields(r["text"], "social", None),
               "attributes": {"platform": _clean(r.get("platform")), "likes": _clean(r.get("likes")), "handle_hash": _clean(r.get("handle_hash"))}}
    elif dataset_type == "survey_responses":
        out = {**base, "external_id": r["response_id"], "occurred_at": r["timestamp"], "numeric_value": r["csat"], "metric_name": "csat",
               "product": None, **_voice_fields(r.get("comment") or "", "survey", r["csat"]),
               "attributes": {"nps": _clean(r.get("nps"))}}
    elif dataset_type == "transactions":
        attrs = {k: _clean(v) for k, v in r.items() if k not in ("order_id", "customer_id", "amount", "order_at")}
        for k in ("promised_at", "delivered_at", "refund_requested_at", "refund_completed_at"):
            attrs[k] = _iso(r.get(k))
        out = {**base, "external_id": r["order_id"], "occurred_at": r["order_at"], "numeric_value": _clean(r.get("amount")),
               "metric_name": "order_value", "product": r.get("product_name") or None, "region": r.get("city") or base["region"],
               "text": None, "sentiment": None, "primary_aspect": None, "aspects": None, "is_flagged": False,
               "flag_reason": None, "attributes": attrs}
    elif dataset_type == "product_telemetry":
        sessions, crashes = float(r["sessions"]), float(r["crashes"])
        ts = pd.to_datetime(r["date"]).normalize() + pd.Timedelta(hours=12)
        out = {"customer_id": None, "segment": None, "region": None, "external_id": f"TEL-{ts.date()}-{r['platform']}-{r.get('os_version') or ''}-{r['app_version']}",
               "occurred_at": ts.to_pydatetime(), "numeric_value": crashes / sessions if sessions else 0.0, "metric_name": "crash_rate",
               "product": "mobile-app", "text": None, "sentiment": None, "primary_aspect": "app", "aspects": None, "is_flagged": False,
               "flag_reason": None, "attributes": {"app_version": r["app_version"], "platform": r["platform"], "os_version": _clean(r.get("os_version")),
                                                   "sessions": int(sessions), "crashes": int(crashes), "p95_latency_ms": _clean(r.get("p95_latency_ms"))}}
    elif dataset_type == "operational_metrics":
        ts = pd.to_datetime(r["date"]).normalize() + pd.Timedelta(hours=12)
        et = r.get("entity_type") or ""
        out = {"customer_id": None, "segment": None, "region": r["entity"] if et == "city" else None,
               "external_id": f"MET-{r['metric_name']}-{r['entity']}-{ts.date()}", "occurred_at": ts.to_pydatetime(),
               "numeric_value": r["value"], "metric_name": r["metric_name"], "product": None, "text": None, "sentiment": None,
               "primary_aspect": None, "aspects": None, "is_flagged": False, "flag_reason": None,
               "attributes": {"entity_type": et or None, "entity": r["entity"], "unit": _clean(r.get("unit"))}}
    else:
        raise ValueError(f"{dataset_type} is not a signal dataset")
    if isinstance(out["occurred_at"], pd.Timestamp):
        out["occurred_at"] = out["occurred_at"].to_pydatetime()
    return out


def _get_source(db: Session, dataset_type: str, name: str | None, user_id, simulated: bool, file_name) -> DataSource:
    spec = DATASETS[dataset_type]
    name = name or spec["label"]
    src = db.scalars(select(DataSource).where(DataSource.name == name, DataSource.source_type == spec["source_type"])).first()
    if src is None:
        src = DataSource(name=name, source_type=spec["source_type"], reliability=spec["reliability"], is_simulated=simulated,
                         description=spec["label"] + (" (simulated)" if simulated else ""), uploaded_by=user_id)
        db.add(src)
        db.flush()
    src.file_name = file_name or src.file_name
    src.last_ingested_at = utcnow()
    return src


def _upsert_segments(db: Session, df: pd.DataFrame) -> int:
    have = {s.code: s for s in db.scalars(select(CustomerSegment))}
    n = 0
    for r in df.to_dict("records"):
        s = have.get(r["segment_code"])
        if s is None:
            db.add(CustomerSegment(code=r["segment_code"], name=r["name"], description=_clean(r.get("description")), rule=_clean(r.get("rule"))))
            n += 1
        else:
            s.name, s.description, s.rule = r["name"], _clean(r.get("description")), _clean(r.get("rule"))
    db.flush()
    return n


def _upsert_customers(db: Session, df: pd.DataFrame) -> int:
    segs = {s.code: s.id for s in db.scalars(select(CustomerSegment))}
    have = {c.customer_ref: c for c in db.scalars(select(Customer))}
    new_rows: list[dict] = []
    for r in df.to_dict("records"):
        vals = dict(city=_clean(r.get("city")), region=_clean(r.get("region")), plan=_clean(r.get("plan")),
                    tenure_days=int(float(r.get("tenure_days") or 0)), lifetime_value=float(r.get("lifetime_value") or 0),
                    platform=_clean(r.get("platform")), os_version=_clean(r.get("os_version")),
                    orders_90d=int(float(r.get("orders_90d") or 0)), complaints_90d=int(float(r.get("complaints_90d") or 0)),
                    segment_id=segs.get(_clean(r.get("segment_code"))))
        c = have.get(r["customer_id"])
        if c is None:
            new_rows.append({"customer_ref": r["customer_id"], **vals})
        else:
            for k, v in vals.items():
                setattr(c, k, v)
    if new_rows:
        db.bulk_insert_mappings(Customer, new_rows)  # one multi-row INSERT instead of a network round trip per customer
    db.flush()
    return len(new_rows)


def _jload(v):
    if isinstance(v, dict):
        return v
    try:
        return json.loads(v) if isinstance(v, str) and v.strip() else {}
    except json.JSONDecodeError:
        return {}


def _upsert_events(db: Session, df: pd.DataFrame, src: DataSource, scenario_id, injected) -> tuple[int, int]:
    have = {e.external_id: e for e in db.scalars(select(OperationalEvent))}
    ins = upd = 0
    new_rows: list[dict] = []
    for r in df.to_dict("records"):
        end = pd.to_datetime(r.get("end_at"), errors="coerce") if r.get("end_at") not in (None, "") else None
        vals = dict(event_type=r["event_type"], title=r["title"], description=_clean(r.get("description")), entity=_clean(r.get("entity")),
                    city=_clean(r.get("city")), scope=_jload(r.get("scope_json")), severity=_clean(r.get("severity")) or "info",
                    start_at=r["start_at"].to_pydatetime(), end_at=end.to_pydatetime() if end is not None and pd.notna(end) else None,
                    attributes=_jload(r.get("attributes_json")) or None, source_id=src.id,
                    reliability=float(r["reliability"]) if str(r.get("reliability") or "").strip() not in ("", "nan") else src.reliability)
        e = have.get(r["event_id"])
        if e is None:
            new_rows.append({"external_id": r["event_id"], "is_injected": injected, "scenario_id": scenario_id, **vals})
            ins += 1
        else:
            for k, v in vals.items():
                setattr(e, k, v)
            upd += 1
    if new_rows:
        db.bulk_insert_mappings(OperationalEvent, new_rows)
    db.flush()
    return ins, upd


def _upsert_releases(db: Session, df: pd.DataFrame, src: DataSource) -> tuple[int, int]:
    have = {e.external_id: e for e in db.scalars(select(ProductRelease))}
    ins = upd = 0
    new_rows: list[dict] = []
    for r in df.to_dict("records"):
        rb = str(r.get("rollback_available", "true")).strip().lower() not in ("false", "0", "no")
        vals = dict(component=r["component"], version=str(r["version"]), title=_clean(r.get("title")), change_summary=_clean(r.get("change_summary")),
                    deployed_at=r["deployed_at"].to_pydatetime(), scope=_jload(r.get("scope_json")), rollback_available=rb,
                    risk_level=_clean(r.get("risk_level")) or "medium", source_id=src.id)
        e = have.get(r["release_id"])
        if e is None:
            new_rows.append({"external_id": r["release_id"], **vals})
            ins += 1
        else:
            for k, v in vals.items():
                setattr(e, k, v)
            upd += 1
    if new_rows:
        db.bulk_insert_mappings(ProductRelease, new_rows)
    db.flush()
    return ins, upd


def ingest(db: Session, dataset_type: str, df: pd.DataFrame, *, source_name: str | None = None, user_id: int | None = None,
           is_simulated: bool = False, file_name: str | None = None, scenario_id: int | None = None, is_injected: bool = False,
           dry_run: bool = False) -> dict:
    t0 = time.time()
    if dataset_type not in DATASETS:
        raise ValueError(f"Unknown dataset type '{dataset_type}'")
    clean, errors, summary = validate(dataset_type, df)
    report = {"dataset_type": dataset_type, "label": DATASETS[dataset_type]["label"], **summary, "errors": errors[:50],
              "inserted": 0, "revised": 0, "unchanged": 0, "flagged_injection": 0, "dry_run": dry_run, "warnings": []}
    if dry_run or clean.empty:
        lk = _Lookup(db) if dataset_type in SIGNAL_DATASETS else None
        if dry_run and lk is not None:
            sample = [normalize_row(dataset_type, r, lk) for r in clean.head(15).to_dict("records")]
            report["preview"] = json.loads(json.dumps(sample, default=str))
        elif dry_run:
            report["preview"] = json.loads(clean.head(15).to_json(orient="records", date_format="iso"))
        return report

    src = _get_source(db, dataset_type, source_name, user_id, is_simulated, file_name)
    if dataset_type == "customer_segments":
        report["inserted"] = _upsert_segments(db, clean)
    elif dataset_type == "customers":
        report["inserted"] = _upsert_customers(db, clean)
    elif dataset_type == "operational_events":
        report["inserted"], report["revised"] = _upsert_events(db, clean, src, scenario_id, is_injected)
    elif dataset_type == "release_history":
        report["inserted"], report["revised"] = _upsert_releases(db, clean, src)
    else:
        stype = DATASETS[dataset_type]["source_type"]
        lookup = _Lookup(db)
        existing = {}
        for sid, ext, h, rev in db.execute(select(CustomerSignal.id, CustomerSignal.external_id, CustomerSignal.content_hash,
                                                  CustomerSignal.revision).where(CustomerSignal.source_type == stype,
                                                                                 CustomerSignal.is_current.is_(True))):
            existing[ext] = (sid, h, rev)
        rows, supersede = [], []
        for r in clean.to_dict("records"):
            sig = normalize_row(dataset_type, r, lookup)
            h = _hash({k: sig[k] for k in ("external_id", "occurred_at", "text", "numeric_value", "attributes", "customer_id")})
            prev = existing.get(sig["external_id"])
            if prev and prev[1] == h:
                report["unchanged"] += 1
                continue
            rev = (prev[2] + 1) if prev else 1
            if prev:
                supersede.append(prev[0])
                report["revised"] += 1
            else:
                report["inserted"] += 1
            if sig.get("is_flagged"):
                report["flagged_injection"] += 1
            rows.append({**sig, "source_id": src.id, "source_type": stype, "revision": rev, "is_current": True, "content_hash": h,
                         "reliability": src.reliability, "is_injected": is_injected, "scenario_id": scenario_id, "ingested_at": utcnow()})
        for i in range(0, len(supersede), 500):
            db.execute(update(CustomerSignal).where(CustomerSignal.id.in_(supersede[i:i + 500])).values(is_current=False))
        if rows:
            db.bulk_insert_mappings(CustomerSignal, rows)
        db.flush()
        if stype in ("review", "ticket", "social", "survey", "transaction"):
            refresh_customer_aggregates(db)
    src.record_count = (src.record_count or 0) + report["inserted"]
    src.rejected_count = (src.rejected_count or 0) + report["rejected"]
    report["source_id"] = src.id
    report["duration_ms"] = int((time.time() - t0) * 1000)
    return report


def refresh_customer_aggregates(db: Session) -> None:
    """Keep complaint-frequency on the customer profile in sync with ingested voice signals."""
    rows = db.execute(select(CustomerSignal.customer_id, CustomerSignal.source_type, CustomerSignal.numeric_value, CustomerSignal.sentiment,
                             CustomerSignal.attributes).where(CustomerSignal.is_current.is_(True), CustomerSignal.customer_id.is_not(None),
                                                              CustomerSignal.source_type.in_(["review", "ticket", "social"]))).all()
    counts: dict[int, int] = {}
    for cid, st, num, sent, attrs in rows:
        cat = (attrs or {}).get("category")
        if nlp.is_negative_voice(st, num if st == "review" else None, sent, cat):
            counts[cid] = counts.get(cid, 0) + 1
    ids = {c for c in counts}
    for c in db.scalars(select(Customer)):
        n = counts.get(c.id, 0)
        if c.complaints_90d != n:
            c.complaints_90d = n
    db.flush()


def ingest_world_frames(db: Session, frames: dict[str, pd.DataFrame], *, user_id=None, scenario_id=None, is_injected=False,
                        only: list[str] | None = None) -> dict[str, dict]:
    """Feed simulator exports through the exact same pipeline that user uploads use."""
    out = {}
    order = ["releases", "events", "reviews", "tickets", "social", "surveys", "transactions", "telemetry", "metrics"]
    for key in order:
        if only and key not in only:
            continue
        df = frames.get(key)
        if df is None or df.empty:
            continue
        dtype = WORLD_FRAME_TO_DATASET[key]
        df = df.copy()
        for c in df.columns:
            if df[c].map(lambda x: isinstance(x, dict)).any():
                df[c] = df[c].map(lambda x: json.dumps(x) if isinstance(x, dict) else x)
        out[key] = ingest(db, dtype, df.astype(str), source_name=f"{DATASETS[dtype]['label']} (simulated)", user_id=user_id,
                          is_simulated=True, scenario_id=scenario_id, is_injected=is_injected)
    return out
