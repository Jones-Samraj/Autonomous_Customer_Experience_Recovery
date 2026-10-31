"""Evidence groundedness: every claim attached to a hypothesis must resolve to real records or be recomputable."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.frames import DataView
from app.models import CustomerSignal, HypothesisEvidence, Intervention, OperationalEvent, ProductRelease, RootCauseHypothesis


def _mask(f: pd.DataFrame, scope: dict) -> pd.Series:
    m = pd.Series(True, index=f.index)
    for k, v in scope.items():
        if k in f.columns:
            m &= f[k].isin(v if isinstance(v, list) else [v])
    return m


def recompute_stat(view: DataView, p: dict) -> tuple[int, int] | None:
    if not p.get("frame") or "where" not in p:
        return None
    f = view.kpi_frame(p["frame"])
    if f.empty:
        return None
    where = p["where"]
    frm = pd.Timestamp(p["from"]) if p.get("from") else None
    time_ok = (f["date"] >= frm) if frm is not None else pd.Series(True, index=f.index)
    if "not" in where:
        base = ~(_mask(f, where["not"]) & time_ok)
    else:
        base = _mask(f, where) & time_ok
    if p.get("onset"):
        base &= f["date"] >= pd.Timestamp(p["onset"])
    rows = f[base]
    return int(rows["n"].sum()), int(rows["k"].sum())


def verify_evidence(db: Session, view: DataView, ev: HypothesisEvidence) -> bool | None:
    """True = grounded, False = ungrounded, None = purely contextual (no checkable claim)."""
    p = ev.payload or {}
    if ev.kind == "statistic":
        if "n" not in p:
            return None
        got = recompute_stat(view, p)
        return got is not None and got == (int(p["n"]), int(p["k"]))
    if ev.kind in ("event", "conflict"):
        if p.get("intervention_id"):  # interventional evidence: the failed action must exist and have been verified as not recovered
            iv = db.get(Intervention, p["intervention_id"])
            return bool(iv and iv.executed_at and iv.verification_status in ("not_recovered", "partial"))
        return bool(ev.event_id and db.get(OperationalEvent, ev.event_id)) if ev.event_id else bool(ev.release_id and db.get(ProductRelease, ev.release_id))
    if ev.kind == "release":
        return bool(ev.release_id and db.get(ProductRelease, ev.release_id))
    if ev.kind in ("metric", "complaint_sample"):
        ids = p.get("signal_ids") or ([ev.signal_id] if ev.signal_id else [])
        if not ids:
            return None
        found = db.scalar(select(func.count()).select_from(CustomerSignal).where(CustomerSignal.id.in_(ids)))  # revisions are retained, so ids stay resolvable
        if found != len(ids):
            return False
        if ev.kind == "complaint_sample" and p.get("terms"):
            texts = [t or "" for (t,) in db.execute(select(CustomerSignal.text).where(CustomerSignal.id.in_(ids)))]
            return all(any(k in t.lower() for k in p["terms"]) for t in texts)
        return True
    return None


def groundedness(db: Session, view: DataView, issue_id: int | None = None) -> dict:
    """Recompute every checkable claim *as the data stood when the hypothesis was produced* (point-in-time replay)."""
    q = select(RootCauseHypothesis).where(RootCauseHypothesis.is_current.is_(True))
    if issue_id:
        q = q.where(RootCauseHypothesis.issue_id == issue_id)
    total = ok = 0
    ungrounded = []
    per_h = {}
    for h in db.scalars(q):
        t = g = 0
        as_of = (h.features or {}).get("as_of")
        hv = DataView(db, datetime.fromisoformat(as_of), view.s, knowledge_time=h.created_at) if as_of and h.created_at else view
        for ev in h.evidence:
            r = verify_evidence(db, hv, ev)
            if r is None:
                continue
            t += 1
            g += 1 if r else 0
            if not r:
                ungrounded.append({"hypothesis_id": h.id, "evidence_id": ev.id, "kind": ev.kind})
        per_h[h.id] = {"checked": t, "grounded": g}
        total, ok = total + t, ok + g
    return {"checked": total, "grounded": ok, "ratio": (ok / total) if total else 1.0, "ungrounded": ungrounded[:20], "per_hypothesis": per_h}
