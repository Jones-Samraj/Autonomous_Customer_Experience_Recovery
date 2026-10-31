"""Agent 2 - Emerging Issue Detection.

Semantic clustering (HDBSCAN on text embeddings) + deterministic statistics (Poisson / two-proportion tests against a
historical baseline, binomial change-point for onset). Clusters are grouped by dominant aspect into issues; structured KPIs
(late deliveries, payment failures, crash rate, ...) corroborate the text signal.
"""
from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd
from sklearn.cluster import HDBSCAN
from sqlalchemy import delete, select, update

from app.agents.context import AgentResult, Ctx
from app.analytics import stats
from app.analytics.frames import KPI_BY_ASPECT, KPI_DIMS
from app.db import utcnow
from app.models import DetectedIssue, IssueCluster, IssueEvidence
from app.services import nlp

log = logging.getLogger("cx.issues")
SEV_CUTS = [(75, "critical"), (55, "high"), (35, "medium"), (0, "low")]


def severity_label(score: float) -> str:
    return next(lbl for cut, lbl in SEV_CUTS if score >= cut)


def _cluster_texts(ctx: Ctx, neg: pd.DataFrame):
    emb = nlp.Embedder(ctx.s.embedding_backend)
    x = emb.fit_transform(neg["text"].tolist())
    labels = HDBSCAN(min_cluster_size=10, min_samples=3, cluster_selection_method="leaf", copy=True).fit_predict(x)
    ids = sorted(set(labels) - {-1})
    if ids:
        cent = np.vstack([x[labels == c].mean(axis=0) for c in ids])
        cent /= np.linalg.norm(cent, axis=1, keepdims=True) + 1e-9
        sims = x @ cent.T
        for i in np.where(labels == -1)[0]:
            j = int(np.argmax(sims[i]))
            if sims[i, j] >= 0.5:
                labels[i] = ids[j]
    return x, labels, emb.name


def _text_stats(counts: pd.Series, w, recent_days: int) -> dict:
    base = counts[counts.index < pd.Timestamp(w.baseline_end)]
    recent = counts[counts.index >= pd.Timestamp(w.recent_start)]
    mean = float(base.mean()) if len(base) else 0.0
    expected = max(mean, 0.15) * len(recent)
    obs = int(recent.sum())
    z, p = stats.poisson_anomaly(obs, expected)
    half = len(recent) // 2 or 1
    h1, h2 = recent.iloc[:half], recent.iloc[half:]
    e1, e2 = max(mean, 0.15) * len(h1), max(mean, 0.15) * len(h2)
    sustained = bool(len(h1) and len(h2) and h1.sum() >= 1.25 * e1 and h2.sum() >= 1.25 * e2 and h1.sum() >= 3 and h2.sum() >= 3)
    thr = mean + 0.5 * math.sqrt(max(mean, 1.0))
    return {"baseline_mean": round(mean, 3), "recent_count": obs, "expected": round(expected, 2), "z": round(z, 2), "p": p,
            "growth": round(obs / expected - 1, 3) if expected >= 1 else None, "sustained": sustained,
            "persistence_days": int((recent > thr).sum()), "is_new": mean < 0.15 and obs >= 8}


def _local_scan(code: str, base: pd.DataFrame, recent: pd.DataFrame, half1: pd.DataFrame, half2: pd.DataFrame, p0: float) -> dict | None:
    """Scan every (dimension, value) sub-population: a localised failure can hide inside a healthy global rate."""
    best = None
    for dim in KPI_DIMS[code]:
        if dim not in recent.columns:
            continue
        for val, g in recent.groupby(dim):
            n_r, k_r = g["n"].sum(), g["k"].sum()
            if n_r < 30 or k_r < 5:
                continue
            b = base[base[dim] == val]
            p_b = max(b["k"].sum() / b["n"].sum() if b["n"].sum() >= 60 else p0, 0.005)
            exp = p_b * n_r
            z = (k_r - exp) / math.sqrt(exp * (1 - p_b) + 1e-9)
            if best is None or z > best["z"]:
                h1, h2 = half1[half1[dim] == val], half2[half2[dim] == val]
                r1 = h1["k"].sum() / h1["n"].sum() if h1["n"].sum() else 0
                r2 = h2["k"].sum() / h2["n"].sum() if h2["n"].sum() else 0
                best = {"dim": dim, "value": str(val), "z": float(z), "rate": float(k_r / n_r), "baseline": float(p_b), "n": int(n_r), "k": int(k_r),
                        "sustained": bool(r1 >= 1.5 * p_b and r2 >= 1.5 * p_b and z >= 4.5)}
    return best if best and best["z"] >= 4.5 else None


def _kpi_stats(ctx: Ctx, aspect: str) -> dict | None:
    if aspect not in KPI_BY_ASPECT:
        return None
    code, label = KPI_BY_ASPECT[aspect]
    f = ctx.view.kpi_frame(code)
    if f.empty:
        return None
    w = ctx.view.w
    # outcomes mature with a lag (delivery, returns, refunds): the recent window ends at the last fully-known cohort day
    last = f["date"].max()
    r_start = max(pd.Timestamp(w.baseline_end), last - pd.Timedelta(days=ctx.s.recent_days - 1))
    base = f[f["date"] < pd.Timestamp(w.baseline_end)]
    recent = f[f["date"] >= r_start]
    if base["n"].sum() < 30 or recent["n"].sum() < 30:
        return None
    p0 = base["k"].sum() / base["n"].sum()
    p1 = recent["k"].sum() / recent["n"].sum()
    z, pv = stats.two_prop_z(recent["k"].sum(), recent["n"].sum(), base["k"].sum(), base["n"].sum())
    mid = r_start + (last - r_start) / 2
    a, b = recent[recent["date"] <= mid.normalize()], recent[recent["date"] > mid.normalize()]
    r1 = a["k"].sum() / a["n"].sum() if a["n"].sum() else 0
    r2 = b["k"].sum() / b["n"].sum() if b["n"].sum() else 0
    sustained = bool(p0 > 0 and r1 >= 1.5 * p0 and r2 >= 1.5 * p0)
    local = _local_scan(code, base, recent, a, b, p0)
    z_eff = max(z, 0.8 * local["z"]) if local else z
    sustained_eff = sustained or bool(local and local["sustained"])
    daily = f.groupby("date")[["n", "k"]].sum().sort_index()
    cp = stats.binom_changepoint(daily["k"].to_numpy(), daily["n"].to_numpy(), 3)
    onset = None
    if cp and cp["p_value"] < 1e-4 and cp["rate_after"] > 1.5 * max(cp["rate_before"], 1e-6):
        onset = daily.index[cp["idx"]]
    return {"code": code, "label": label, "baseline_rate": float(p0), "current_rate": float(p1), "z": float(z), "p": pv, "z_eff": float(z_eff),
            "local": local, "sustained_eff": sustained_eff,
            "ratio": float(p1 / p0) if p0 > 0 else None, "sustained": sustained, "onset": onset, "n_recent": int(recent["n"].sum()),
            "k_recent": int(recent["k"].sum()), "n_base": int(base["n"].sum()), "k_base": int(base["k"].sum())}


MATURITY_DAYS = {"late_delivery_rate": 2.5, "defect_return_rate": 7.0, "refund_sla_breach_rate": 5.0, "payment_failure_rate": 0.0, "crash_rate": 0.0}


def _isolation_check(clustered: pd.DataFrame, days: pd.DatetimeIndex, w) -> dict:
    """Multivariate anomaly cross-check: IsolationForest trained on baseline days of per-aspect complaint counts, scored on recent days."""
    from sklearn.ensemble import IsolationForest

    m = clustered.groupby(["date", "primary_aspect"]).size().unstack(fill_value=0).reindex(days, fill_value=0)
    base = m[m.index < pd.Timestamp(w.baseline_end)]
    recent = m[m.index >= pd.Timestamp(w.recent_start)]
    if len(base) < 7 or m.shape[1] < 2 or recent.empty:
        return {}
    clf = IsolationForest(n_estimators=200, contamination=0.05, random_state=7).fit(base.to_numpy())
    flagged = clf.predict(recent.to_numpy()) == -1
    mu, sd = base.mean(), base.std(ddof=1).replace(0, 1)
    out = {"_overall": {"flagged_days": int(flagged.sum()), "recent_days": int(len(recent))}}
    for a in m.columns:
        elevated = ((recent[a] - mu[a]) / sd[a]).to_numpy() > 1.5
        out[a] = {"flagged_days": int((flagged & elevated).sum()), "recent_days": int(len(recent))}
    return out


def _first_detected(ctx: Ctx, counts: pd.Series, mean: float, kpi: dict | None, onset) -> pd.Timestamp:
    """Earliest day on which cumulative post-onset evidence (text or structured KPI, after outcome maturity) crossed the threshold."""
    start = pd.Timestamp(onset).normalize() if onset is not None else pd.Timestamp(ctx.view.w.baseline_end)
    found = []
    cum, days = 0, 0
    for d, c in counts[counts.index >= start].items():
        cum += int(c)
        days += 1
        _, p = stats.poisson_anomaly(cum, max(mean, 0.15) * days)
        if p < 0.005 and cum >= 6:
            found.append(d + pd.Timedelta(days=1))
            break
    if kpi:
        f = ctx.view.kpi_frame(kpi["code"])
        daily = f[f["date"] >= start].groupby("date")[["n", "k"]].sum()
        ck = cn = 0
        for d, r in daily.iterrows():
            ck, cn = ck + r["k"], cn + r["n"]
            if cn >= 25 and ck >= 4 and stats.two_prop_z(ck, cn, kpi["k_base"], kpi["n_base"])[0] >= 3.5:
                found.append(d + pd.Timedelta(days=1 + MATURITY_DAYS.get(kpi["code"], 0)))
                break
    return min(found) if found else start + pd.Timedelta(days=1)


def _evidence(ctx: Ctx, aspect, kpi, onset, group_rows: pd.DataFrame, x_by_id: dict) -> tuple[list[dict], int]:
    """Evidence = grouped complaints since onset + structural bad-outcome records. Flags duplicate reports."""
    out: list[dict] = []
    since = pd.Timestamp(onset).normalize() - pd.Timedelta(days=2) if onset is not None else pd.Timestamp(ctx.view.w.baseline_end)
    g = group_rows[group_rows["occurred_at"] >= since].sort_values("occurred_at")
    seen: dict[tuple, pd.Timestamp] = {}
    dups = 0
    for r in g.itertuples():
        key = (r.customer_id, aspect) if not pd.isna(r.customer_id) else None
        is_dup = False
        if key and key in seen and (r.occurred_at - seen[key]) <= pd.Timedelta(hours=24):
            is_dup = True
            dups += 1
        elif key:
            seen[key] = r.occurred_at
        out.append({"signal_id": int(r.id), "cluster_label": int(r.cluster), "relevance": round(float(x_by_id.get(int(r.id), 1.0)), 3), "is_duplicate": is_dup})
    if kpi:
        f = ctx.view.kpi_frame(kpi["code"])
        bad = f[(f["k"] > 0) & (f["date"] >= since)].sort_values("date", ascending=False).head(400)
        for sid in bad["signal_id"].dropna().astype(int):
            out.append({"signal_id": int(sid), "cluster_label": None, "relevance": 1.0, "is_duplicate": False})
    return out, dups


def run(ctx: Ctx) -> AgentResult:
    db, w = ctx.db, ctx.view.w
    v = ctx.view.voice()
    neg = v[v["negative"] & ~v["is_flagged"] & v["text"].fillna("").str.len().gt(12)].copy().reset_index(drop=True) if not v.empty else v
    if len(neg) < 30:
        return AgentResult(output={"issues": [], "clusters": 0}, reasoning="Not enough negative customer-voice signals to cluster.", status="succeeded")
    x, labels, backend = _cluster_texts(ctx, neg)
    neg["cluster"] = labels
    clustered = neg[neg["cluster"] >= 0]
    days = pd.date_range(pd.Timestamp(w.data_start).normalize(), pd.Timestamp(w.now).normalize() - pd.Timedelta(days=1))

    clusters = []
    for c, g in clustered.groupby("cluster"):
        aspect = g["primary_aspect"].mode().iat[0]
        counts = g.groupby("date").size().reindex(days, fill_value=0)
        ts = _text_stats(counts, w, ctx.s.recent_days)
        terms = nlp.top_terms(g["text"].tolist(), 5)
        clusters.append({"label_id": int(c), "aspect": aspect, "size": int(len(g)), "terms": terms, "counts": counts, "stats": ts,
                         "title": f"{nlp.ASPECT_LABEL.get(aspect, aspect)}: " + ", ".join(terms[:3])})
    by_aspect: dict[str, list[dict]] = {}
    for c in clusters:
        by_aspect.setdefault(c["aspect"], []).append(c)

    iso_check = _isolation_check(clustered, days, w)
    run_clusters, issues_out, watch_out = [], [], []
    existing = {i.aspect: i for i in db.scalars(select(DetectedIssue)) if i.status != "superseded"}
    db.execute(update(IssueEvidence).values(cluster_id=None))
    db.execute(delete(IssueCluster))
    for aspect in sorted(set(by_aspect) | set(KPI_BY_ASPECT)):
        groups = by_aspect.get(aspect, [])
        gids = [c["label_id"] for c in groups]
        grows = clustered[clustered["primary_aspect"] == aspect]
        counts = grows.groupby("date").size().reindex(days, fill_value=0) if len(grows) else pd.Series(0, index=days)
        ts = _text_stats(counts, w, ctx.s.recent_days)
        kpi = _kpi_stats(ctx, aspect)
        text_ok = ts["sustained"] and ts["p"] < 1e-3 and ts["recent_count"] >= ctx.s.min_issue_support
        kpi_ok = bool(kpi and kpi["sustained_eff"] and kpi["z_eff"] >= 4 and (kpi["ratio"] or 0) >= 1.5)
        # two independent sources that are each moderately significant corroborate one another (Stouffer-combined z)
        combined_ok = bool(kpi and ts["z"] >= 2 and kpi["z_eff"] >= 2 and (ts["z"] + kpi["z_eff"]) / math.sqrt(2) >= 4.5
                           and (ts["sustained"] or kpi["sustained_eff"]) and (kpi["ratio"] or 0) >= 1.5)
        kpi_ok = kpi_ok or combined_ok
        any_signal = (ts["p"] < 0.01 and ts["recent_count"] >= 5) or bool(kpi and kpi["z_eff"] >= 3)
        if not (text_ok or kpi_ok or any_signal) or (aspect == "other" and not text_ok):
            continue

        onset = kpi["onset"] if kpi and kpi["onset"] is not None else None
        if onset is None and len(counts):
            thr = ts["baseline_mean"] + 1.5 * math.sqrt(max(ts["baseline_mean"], 1.0))
            post = counts[counts.index >= pd.Timestamp(w.baseline_end)]
            roll = post.rolling(3).sum()
            hit = roll[roll >= 3 * thr * 0.8]
            onset = hit.index[0] - pd.Timedelta(days=2) if len(hit) else pd.Timestamp(w.recent_start)
        types = grows["source_type"].nunique() if len(grows) else 0
        if kpi:
            types += 1
        diversity = min(1.0, types / 4)
        text_strength = min(1.0, max(0.0, ts["z"]) / 6) if text_ok or ts["z"] > 0 else 0.0
        kpi_strength = min(1.0, max(0.0, kpi["z_eff"]) / 8) if kpi else None
        persistence = (1.0 if ts["sustained"] else 0.4) if kpi is None else (1.0 if kpi["sustained_eff"] or ts["sustained"] else 0.4)
        if kpi_strength is not None:
            conf = 0.35 * text_strength + 0.35 * kpi_strength + 0.2 * diversity + 0.1 * persistence
        else:
            conf = 0.6 * text_strength + 0.25 * diversity + 0.15 * persistence
        conf = min(conf, 0.99)
        detected = (text_ok or kpi_ok) and conf >= 0.5
        if not detected:
            conf = min(conf, 0.45)

        ev, dups = _evidence(ctx, aspect, kpi, onset, grows.assign(cluster=grows["cluster"]), {})
        support = len({e["signal_id"] for e in ev if not e["is_duplicate"]})
        mean_sent = float(grows["sentiment"].mean()) if len(grows) else 0.0
        cust = ctx.view.customers()
        affected_ids = set(grows[grows["occurred_at"] >= pd.Timestamp(onset) - pd.Timedelta(days=2)]["customer_id"].dropna().astype(int)) if onset is not None else set()
        if kpi:
            kf = ctx.view.kpi_frame(kpi["code"])
            affected_ids |= set(kf[(kf["k"] > 0) & (kf["date"] >= pd.Timestamp(onset))]["customer_id"].dropna().astype(int)) if onset is not None else set()
        tx = ctx.view.tx()
        active = set(tx[tx["order_at"] >= pd.Timestamp(w.now) - pd.Timedelta(days=14)]["customer_id"].dropna().astype(int)) | affected_ids if not tx.empty else affected_ids
        breadth = len(affected_ids) / max(len(active), 1)
        ltv_all = cust["lifetime_value"].mean() or 1.0
        ltv_aff = cust[cust["customer_id"].isin(affected_ids)]["lifetime_value"].mean() if affected_ids else ltv_all
        growth = ts["growth"] if ts["growth"] is not None else 0.0
        comps = {"growth": min(1.0, max(growth, 0) / 2), "breadth": min(1.0, breadth / 0.15), "volume": min(1.0, ts["recent_count"] / 40),
                 "negative_sentiment": min(1.0, max(0.0, -mean_sent) / 0.6),
                 "kpi_deviation": min(1.0, max((kpi["ratio"] or 1) - 1, 0) / 3) if kpi else 0.0,
                 "customer_value": min(1.0, float(ltv_aff) / float(ltv_all) / 2) if ltv_all else 0.0}
        weights = {"growth": 0.20, "breadth": 0.25, "kpi_deviation": 0.25, "volume": 0.10, "negative_sentiment": 0.10, "customer_value": 0.10}
        score = 100 * sum(comps[k] * weights[k] for k in comps)
        first_det = _first_detected(ctx, counts, ts["baseline_mean"], kpi, onset)
        label = nlp.ASPECT_LABEL.get(aspect, aspect)
        if aspect == "other":
            label = "Emerging issue: " + ", ".join((groups[0]["terms"][:3] if groups else []) or ["unclassified"])
        if kpi:
            title = f"{label}: {kpi['label'].lower()} up {kpi['ratio']:.1f}x vs baseline" if kpi.get("ratio") else f"{label}: {kpi['label'].lower()} rising"
            desc = (f"{kpi['label']} rose from {kpi['baseline_rate']:.1%} (baseline) to {kpi['current_rate']:.1%} over the last {w.recent_days} days "
                    f"(z={kpi['z']:.1f}). Customer complaints about {label.lower()} reached {ts['recent_count']} in the same window versus "
                    f"{ts['expected']:.0f} expected from the historical baseline.")
            loc = kpi.get("local")
            if loc and loc["z"] > kpi["z"]:
                desc += f" The failure is localised: {loc['dim'].replace('_', ' ')} = {loc['value']} runs at {loc['rate']:.1%} against {loc['baseline']:.1%} baseline (z={loc['z']:.1f})."
        else:
            title = f"{label}: complaint volume up {ts['recent_count'] / max(ts['expected'], 1):.1f}x vs baseline"
            desc = (f"{ts['recent_count']} {label.lower()} complaints in the last {w.recent_days} days versus {ts['expected']:.0f} expected "
                    f"from the historical baseline (z={ts['z']:.1f}).")
        stats_json = {"text": {k: (float(v) if isinstance(v, (np.floating, float)) else v) for k, v in ts.items()},
                      "kpi": ({k: (v.isoformat() if isinstance(v, pd.Timestamp) else v) for k, v in kpi.items()} if kpi else None),
                      "embedding_backend": backend, "isolation_forest": iso_check.get(aspect), "clusters": gids, "daily_counts": {d.strftime("%Y-%m-%d"): int(c) for d, c in counts.items()},
                      "confidence_components": {"text": round(text_strength, 3), "kpi": None if kpi_strength is None else round(kpi_strength, 3),
                                                "source_diversity": round(diversity, 3), "persistence": persistence}}
        issue = existing.get(aspect)
        brand_new = issue is None
        if brand_new:
            issue = DetectedIssue(code="PENDING", aspect=aspect, category=label, title=title, status="watchlist")
            db.add(issue)
            db.flush()
            issue.code = f"ISS-{issue.id:04d}"
            issue.first_detected_at = first_det.to_pydatetime()
        prev = issue.status
        if detected:
            if prev == "resolved":
                issue.status, issue.reopen_count = "reopened", issue.reopen_count + 1
            elif brand_new or prev == "watchlist":
                issue.status = "open"
        elif brand_new or prev == "watchlist":
            issue.status = "watchlist"
        issue.title, issue.description, issue.category = title, desc, label
        issue.severity_score, issue.severity = round(score, 1), severity_label(score)
        issue.severity_breakdown = {"components": {k: round(v, 3) for k, v in comps.items()}, "weights": weights}
        issue.detection_confidence = round(conf, 3)
        issue.support_count, issue.duplicate_count = support, dups
        issue.growth_rate = round(growth, 3)
        issue.kpi_name = kpi["code"] if kpi else None
        issue.baseline_rate = kpi["baseline_rate"] if kpi else ts["baseline_mean"]
        issue.current_rate = kpi["current_rate"] if kpi else ts["recent_count"] / max(w.recent_days, 1)
        issue.onset_at = pd.Timestamp(onset).to_pydatetime() if onset is not None else None
        issue.stats = stats_json
        issue.updated_at = utcnow()
        db.flush()
        db.execute(delete(IssueEvidence).where(IssueEvidence.issue_id == issue.id))
        cl_rows = {}
        for cdef in groups:
            row = IssueCluster(issue_id=issue.id, run_id=ctx.run_id, cluster_label=cdef["label_id"], label=cdef["title"], top_terms=cdef["terms"],
                               aspect=aspect, size=cdef["size"], daily_counts={d.strftime("%Y-%m-%d"): int(c) for d, c in cdef["counts"].items()},
                               baseline_mean=cdef["stats"]["baseline_mean"], recent_count=cdef["stats"]["recent_count"],
                               expected_count=cdef["stats"]["expected"], z_score=cdef["stats"]["z"], p_value=cdef["stats"]["p"],
                               growth_rate=cdef["stats"]["growth"], persistence_days=cdef["stats"]["persistence_days"],
                               is_new=cdef["stats"]["is_new"], is_anomalous=cdef["stats"]["sustained"] and cdef["stats"]["p"] < 0.01)
            db.add(row)
            db.flush()
            cl_rows[cdef["label_id"]] = row.id
        seen_sig = set()
        ev_rows = []
        for e in ev:
            if e["signal_id"] in seen_sig:
                continue
            seen_sig.add(e["signal_id"])
            ev_rows.append({"issue_id": issue.id, "signal_id": e["signal_id"], "cluster_id": cl_rows.get(e["cluster_label"]), "relevance": e["relevance"],
                            "is_duplicate": e["is_duplicate"]})
        if ev_rows:
            db.bulk_insert_mappings(IssueEvidence, ev_rows)  # evidence rows are write-only: batch them instead of one round trip each
        row = {"id": issue.id, "code": issue.code, "aspect": aspect, "title": issue.title, "severity": issue.severity, "severity_score": issue.severity_score,
               "confidence": issue.detection_confidence, "support": support, "growth": issue.growth_rate, "status": issue.status,
               "onset": issue.onset_at.isoformat() if issue.onset_at else None}
        (issues_out if issue.status != "watchlist" else watch_out).append(row)
        run_clusters.extend(groups)
    # clusters that belong to no issue are still stored for the Issue Intelligence view
    issue_aspects = {r["aspect"] for r in issues_out + watch_out}
    for c in clusters:
        if c["aspect"] not in issue_aspects:
            db.add(IssueCluster(issue_id=None, run_id=ctx.run_id, cluster_label=c["label_id"], label=c["title"], top_terms=c["terms"], aspect=c["aspect"],
                                size=c["size"], daily_counts={d.strftime("%Y-%m-%d"): int(n) for d, n in c["counts"].items()},
                                baseline_mean=c["stats"]["baseline_mean"], recent_count=c["stats"]["recent_count"], expected_count=c["stats"]["expected"],
                                z_score=c["stats"]["z"], p_value=c["stats"]["p"], growth_rate=c["stats"]["growth"],
                                persistence_days=c["stats"]["persistence_days"], is_new=c["stats"]["is_new"], is_anomalous=False))
    db.flush()
    reasoning = (f"Clustered {len(clustered)} of {len(neg)} negative customer-voice signals into {len(clusters)} semantic clusters ({backend}); "
                 f"tested each aspect against the first {w.baseline_days}-day baseline with Poisson and two-proportion tests; confirmed "
                 f"{len(issues_out)} issue(s) and {len(watch_out)} watchlist item(s).")
    return AgentResult(output={"issues": issues_out, "watchlist": watch_out, "clusters": len(clusters), "signals_clustered": int(len(clustered)),
                               "embedding_backend": backend}, reasoning=reasoning,
                       inputs={"negative_signals": int(len(neg)), "baseline_days": w.baseline_days, "recent_days": w.recent_days})
