"""Agent 4 - Root Cause Investigation.

Generates competing hypotheses from operational events, releases, continuous metrics and known mechanism templates, then
scores each one against the structured KPI frame with deterministic statistics:

* temporal precedence        - did the change start before the issue onset?
* coverage                   - how much of the total excess falls inside the hypothesis' exposure group?
* adjusted attribution       - Mantel-Haenszel effect after conditioning on every competing hypothesis (confounding control)
* sufficiency / homogeneity  - is the effect present in *all* exposed sub-groups, or only some?
* residual unexplained excess- excess outside the exposure group contradicts the hypothesis
* text corroboration         - mechanism terms in complaints that were absent at baseline
* direct measurement         - a diagnostic metric that is normal contradicts; an elevated one supports

Confidence is capped below certainty: correlation is never presented as proven causation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sqlalchemy import select, update

from app.agents.context import AgentResult, Ctx
from app.agents.domain import ASPECT_CAUSES, CAUSE_LABEL, INTERVENTIONS, SEVERITY_ORDER
from app.analytics import stats
from app.analytics.frames import KPI_BY_ASPECT, KPI_DIMS
from app.db import utcnow
from app.models import DetectedIssue, HypothesisEvidence, Intervention, RootCauseHypothesis

DIM_LABEL = {"delivery_partner": "delivery partner", "city": "city", "gateway": "gateway", "payment_method": "payment method",
             "app_version": "app version", "platform": "platform", "os_version": "OS version", "supplier": "supplier", "batch": "batch",
             "sku": "SKU", "category": "category", "refund_type": "refund type", "warehouse": "warehouse", "plan": "plan"}
METRIC_LABEL = {"traffic_congestion_index": "traffic congestion index", "warehouse_dispatch_hours": "warehouse dispatch time",
                "gateway_availability": "gateway availability", "refund_queue_depth": "refund queue depth",
                "support_backlog": "support backlog", "api_p95_latency_ms": "API p95 latency"}
CONF_CAP = 0.90


@dataclass
class Cand:
    tmpl: dict
    title: str
    scope: dict
    start: pd.Timestamp | None
    kind: str  # event | release | metric | template
    anchors: list = field(default_factory=list)  # (kind, orm_object)
    mask: pd.Series | None = None
    scope_mask: pd.Series | None = None
    no_data: bool = False
    metric: dict | None = None
    metric_flat: bool = False
    refined: str | None = None
    f: dict = field(default_factory=dict)
    ev: list = field(default_factory=list)

    @property
    def cause_type(self) -> str:
        return self.tmpl["cause_type"]


def _scope_text(scope: dict) -> str:
    return ", ".join(f"{DIM_LABEL.get(k, k)} = {v if not isinstance(v, list) else '/'.join(map(str, v))}" for k, v in scope.items()) or "all units"


def _apply_scope(f: pd.DataFrame, scope: dict) -> tuple[pd.Series, dict]:
    m = pd.Series(True, index=f.index)
    applied = {}
    for k, v in (scope or {}).items():
        if k in f.columns and v not in (None, ""):
            vals = v if isinstance(v, list) else [v]
            m &= f[k].isin(vals)
            applied[k] = v
    return m, applied


def _metric_elevation(ctx: Ctx, name: str, low_is_bad: bool, onset: pd.Timestamp) -> dict | None:
    m = ctx.view.metrics()
    if m.empty:
        return None
    m = m[m["metric_name"] == name]
    if m.empty:
        return None
    base_end = pd.Timestamp(ctx.view.w.baseline_end)
    sign = -1.0 if low_is_bad else 1.0
    out = {}
    for ent, g in m.groupby("entity"):
        g = g.sort_values("date")
        base = g[g["date"] < base_end]["value"]
        post = g[g["date"] >= onset - pd.Timedelta(days=3)]
        if len(base) < 5 or post.empty:
            continue
        mu, sd = float(base.mean()), max(float(base.std(ddof=1)), 1e-6)
        z = sign * (float(post["value"].mean()) - mu) / sd
        zs = sign * (g["value"] - mu) / sd
        hit = g[(g["date"] >= onset - pd.Timedelta(days=3)) & (zs >= 2)]
        top = post.assign(_z=sign * (post["value"] - mu) / sd).sort_values("_z", ascending=False).head(3)
        out[ent] = {"z": z, "start": hit["date"].min() if len(hit) else None, "mean_post": float(post["value"].mean()), "mean_base": mu, "sd": sd,
                    "signal_ids": [int(x) for x in top["signal_id"]], "entity_type": g["entity_type"].iat[0]}
    return out or None


def _build_candidates(ctx: Ctx, issue: DetectedIssue, f: pd.DataFrame, onset: pd.Timestamp) -> list[Cand]:
    aspect = issue.aspect
    cands: list[Cand] = []
    dims = set(f.columns)
    ev_back, rel_back = (28, 24) if ctx.flags.get("widen_lookback") else (14, 12)
    for tmpl in ASPECT_CAUSES.get(aspect, []):
        found = False
        for ev in ctx.view.events():
            if SEVERITY_ORDER.get(ev.severity or "info", 0) < 1 or ev.event_type not in tmpl.get("events", []):
                continue
            if pd.Timestamp(ev.start_at) < onset - pd.Timedelta(days=ev_back):
                continue
            mask, applied = _apply_scope(f, ev.scope or {})
            start = pd.Timestamp(ev.start_at).normalize()
            c = Cand(tmpl, ev.title, applied, start, "event", [("event", ev)], mask & (f["date"] >= start), mask)
            cands.append(c)
            found = True
        for rel in ctx.view.releases():
            if rel.component not in tmpl.get("components", []):
                continue
            if not (onset - pd.Timedelta(days=rel_back) <= pd.Timestamp(rel.deployed_at) <= pd.Timestamp(ctx.now)):
                continue
            mask, applied = _apply_scope(f, rel.scope or {})
            start = pd.Timestamp(rel.deployed_at).normalize()
            cands.append(Cand(tmpl, f"{rel.component} {rel.version}: {rel.title}", applied, start, "release", [("release", rel)], mask & (f["date"] >= start), mask))
            found = True
        if tmpl.get("metric"):
            elev = _metric_elevation(ctx, tmpl["metric"], bool(tmpl.get("low_is_bad")), onset)
            if elev is None:
                if tmpl.get("gap_ok") and not found:
                    cands.append(Cand(tmpl, f"{CAUSE_LABEL[tmpl['cause_type']]} (no diagnostic data connected)", {}, None, "template", no_data=True))
                continue
            hot = {e: v for e, v in elev.items() if v["z"] >= 2.0 and v["start"] is not None}
            label = METRIC_LABEL.get(tmpl["metric"], tmpl["metric"])
            if hot:
                dim = tmpl.get("metric_dim")
                start = min(v["start"] for v in hot.values())
                if dim in dims:
                    ents = sorted(hot)
                    mask = f[dim].isin(ents) & (f["date"] >= start)
                    scope_mask, scope = f[dim].isin(ents), {dim: ents}
                else:
                    mask, scope_mask, scope = f["date"] >= start, pd.Series(True, index=f.index), {}
                verb = "degraded" if tmpl.get("low_is_bad") else "elevated"
                title = f"{CAUSE_LABEL[tmpl['cause_type']]}: {label} {verb}" + (f" in {', '.join(sorted(hot))}" if dim in dims else "")
                cands.append(Cand(tmpl, title, scope, start, "metric", [], mask, scope_mask, metric={"label": label, "name": tmpl["metric"], "entities": elev, "hot": hot}))
            elif not found:
                worst = max(elev.values(), key=lambda v: v["z"])
                cands.append(Cand(tmpl, f"{CAUSE_LABEL[tmpl['cause_type']]}: {label} within normal range", {}, None, "metric",
                                  [], pd.Series(False, index=f.index), pd.Series(False, index=f.index), metric={"label": label, "name": tmpl["metric"], "entities": elev, "hot": {}, "max_z": worst["z"]},
                                  metric_flat=True))
    return cands


def _jaccard(a: pd.Series, b: pd.Series) -> float:
    u = (a | b).sum()
    return float((a & b).sum() / u) if u else 0.0


def _text_mentions(ctx: Ctx, issue, c: Cand, onset) -> dict:
    v = ctx.view.voice()
    v = v[v["negative"] & ~v["is_flagged"] & (v["primary_aspect"] == issue.aspect)]
    if v.empty:
        return {"lift": 0.0, "post": 0, "sample": [], "terms": []}
    terms = {t.lower() for t in c.tmpl.get("keywords", [])}
    for val in c.scope.values():
        for x in (val if isinstance(val, list) else [val]):
            if isinstance(x, str) and len(x) > 3 and x not in ("Card", "UPI"):
                terms.add(x.lower())
    for _, obj in c.anchors:
        if _ == "release":
            terms.add(obj.version.lower())
    txt = v["text"].str.lower()
    hit = txt.apply(lambda t: any(k in t for k in terms)) if terms else pd.Series(False, index=v.index)
    base = v["date"] < pd.Timestamp(ctx.view.w.baseline_end)
    post = v["date"] >= onset
    m_post = hit[post].mean() if post.any() else 0.0
    m_base = hit[base].mean() if base.any() else 0.0
    sample = v[post & hit].sort_values("occurred_at", ascending=False).head(3)
    return {"lift": max(0.0, float(m_post - m_base)), "post": int(hit[post].sum()), "m_post": float(m_post), "m_base": float(m_base),
            "sample": [(int(i), t) for i, t in zip(sample["id"], sample["text"])], "terms": sorted(terms)}


def _evaluate(f: pd.DataFrame, c: Cand, onset, base_end, p0: float, others: list["Cand"], tot_excess: float) -> dict:
    post = f["date"] >= onset
    pre = f["date"] < base_end
    out: dict = {}
    if c.mask is None or not c.mask.any() or c.metric_flat:
        return {"exposed_n": 0, "has_control": False, "coverage": 0.0, "residual": 0.0, "attribution": None, "violation": 0.0}
    mask, scope_mask = c.mask, c.scope_mask if c.scope_mask is not None else c.mask
    E, U = post & mask, post & ~mask
    n_e, k_e, n_u, k_u = f.loc[E, "n"].sum(), f.loc[E, "k"].sum(), f.loc[U, "n"].sum(), f.loc[U, "k"].sum()
    p0_e = f.loc[pre & scope_mask, "k"].sum() / f.loc[pre & scope_mask, "n"].sum() if f.loc[pre & scope_mask, "n"].sum() >= 30 else p0
    pre_u = pre & ~scope_mask
    p0_u = f.loc[pre_u, "k"].sum() / f.loc[pre_u, "n"].sum() if f.loc[pre_u, "n"].sum() >= 30 else p0
    rate_e = k_e / n_e if n_e else 0.0
    rate_u = k_u / n_u if n_u else 0.0
    excess_e = k_e - p0_e * n_e
    excess_u = k_u - p0_u * n_u
    cov = float(np.clip(excess_e / tot_excess, 0, 1)) if tot_excess > 0 else 0.0
    resid = float(np.clip(max(excess_u, 0) / tot_excess, 0, 1)) if tot_excess > 0 else 0.0
    z_u = excess_u / math.sqrt(max(p0_u * (1 - p0_u) * n_u, 1e-9)) if n_u else 0.0
    z_eu = stats.two_prop_z(k_e, n_e, k_u, n_u)[0] if n_u else None
    has_control = bool(n_u >= 10 and n_e >= 20)
    # adjusted contrast: exposed vs unexposed (incl. pre-period) within strata of each overlapping competitor
    adj, adj_vs, adj_detail = None, None, []
    for o in others:
        if o is c or o.mask is None or not o.mask.any() or o.metric_flat:
            continue
        ov = f.loc[E & o.mask, "n"].sum()
        if ov < 0.2 * max(f.loc[E, "n"].sum(), 1) or _jaccard(E, post & o.mask) > 0.98:
            continue
        r = stats.mh_risk_difference(f.assign(__s=o.mask.to_numpy()), mask, ["__s"])
        if r is not None:
            adj_detail.append({"vs": o.title, "rd": r["rd"], "se": r["se"], "z": r["z"]})
            if adj is None or r["rd"] < adj:
                adj, adj_vs = r["rd"], o.title
    if adj is None:
        r0 = stats.mh_risk_difference(f.assign(__s=0), mask, ["__s"])
        adj_unconditioned = r0["rd"] if r0 else None
    else:
        adj_unconditioned = None
    denom = max(rate_e - p0_e, 1e-6)
    attribution = float(np.clip(adj / denom, 0, 1)) if adj is not None else (
        float(np.clip(adj_unconditioned / denom, 0, 1)) if adj_unconditioned is not None else None)
    # sufficiency: sub-groups of the exposed units that show no excess
    viol, dead = 0.0, []
    for dim in KPI_DIMS[c.f["kpi"]]:
        if dim in c.scope or dim not in f.columns:
            continue
        for val, g in f[E].groupby(dim):
            if g["n"].sum() < 0.2 * n_e or g["n"].sum() < 20:
                continue
            r_sub = g["k"].sum() / g["n"].sum()
            if (r_sub - p0_e) < 0.25 * max(rate_e - p0_e, 1e-9):
                dead.append({"dim": dim, "value": str(val), "share": float(g["n"].sum() / n_e), "rate": float(r_sub), "n": int(g["n"].sum()), "k": int(g["k"].sum())})
    if dead:
        by_dim = {}
        for d in dead:
            by_dim[d["dim"]] = by_dim.get(d["dim"], 0) + d["share"]
        viol = float(min(1.0, max(by_dim.values())))
    out.update({"exposed_n": int(n_e), "exposed_k": int(k_e), "unexposed_n": int(n_u), "unexposed_k": int(k_u), "rate_exposed": rate_e, "rate_unexposed": rate_u,
                "p0_exposed": p0_e, "p0_unexposed": p0_u, "excess_exposed": float(excess_e), "excess_unexposed": float(excess_u), "coverage": cov, "residual": resid,
                "z_unexposed": z_u, "z_contrast": z_eu, "has_control": has_control, "adj_rd": adj, "adj_vs": adj_vs, "adj_detail": adj_detail,
                "attribution": attribution, "violation": viol, "dead_subgroups": dead[:4], "total_excess": float(tot_excess)})
    return out


def _refine(f: pd.DataFrame, c: Cand, onset, p0: float, taken: list[pd.Series]) -> bool:
    """Narrow a release hypothesis to the sub-population where the excess concentrates (e.g. app 7.8.0 on Android 14)."""
    post = f["date"] >= onset
    E = post & c.mask
    if f.loc[E, "n"].sum() < 40:
        return False
    best = None
    for dim in KPI_DIMS[c.f["kpi"]]:
        if dim in c.scope or dim not in f.columns:
            continue
        ex_tot = f.loc[E, "k"].sum() - p0 * f.loc[E, "n"].sum()
        if ex_tot <= 0:
            return False
        for val, g in f[E].groupby(dim):
            share_ex = (g["k"].sum() - p0 * g["n"].sum()) / ex_tot
            share_n = g["n"].sum() / f.loc[E, "n"].sum()
            if share_ex >= 0.8 and share_n <= 0.6 and (best is None or share_n < best[3]):
                best = (dim, val, share_ex, share_n)
    if not best:
        return False
    dim, val, _, _ = best
    new_mask = c.mask & (f[dim] == val)
    if any(_jaccard(post & new_mask, post & t) > 0.9 for t in taken):
        return False
    c.mask, c.scope = new_mask, {**c.scope, dim: val}
    c.scope_mask = c.scope_mask & (f[dim] == val)
    c.refined = f"{DIM_LABEL.get(dim, dim)} {val}"
    c.title += f" (concentrated on {DIM_LABEL.get(dim, dim)} {val})"
    return True


def _score(c: Cand, tm: dict, lag: int | None) -> tuple[float, dict]:
    f = c.f
    if c.no_data:
        return min(CONF_CAP, c.tmpl["prior"] * 0.4), {"no_data": True}
    temporal, after = 0.5, False
    if lag is not None:
        if lag < -1:
            temporal, after = 0.0, True
        elif lag <= 7:
            temporal = 1.0
        elif lag <= 14:
            temporal = 0.6
        else:
            temporal = 0.3
    metric_support = 0.0
    contradiction = 0.0
    if c.metric is not None:
        if c.metric_flat:
            contradiction = 1.0
        elif c.metric["hot"]:
            metric_support = float(min(1.0, max(v["z"] for v in c.metric["hot"].values()) / 6))
    if after:
        contradiction = max(contradiction, 1.0)
    cov, resid, viol = f.get("coverage", 0.0), f.get("residual", 0.0), f.get("violation", 0.0)
    attribution = f.get("attribution")
    explained = cov * attribution if attribution is not None else cov * 0.5
    text = float(np.clip(tm["lift"] / 0.25, 0, 1))
    conflict = 0.25 * c.f.get("conflict_weight", 0.0)
    S = (-3.0 + 1.2 * temporal + 3.6 * explained + 0.9 * text + 0.8 * c.tmpl["prior"] - 1.8 * resid - 1.2 * viol - 2.5 * contradiction
         + 0.8 * metric_support - conflict)
    if not f.get("has_control") and not c.metric_flat:
        S = min(S, -0.4)
    parts = {"temporal": temporal, "explained": explained, "text": text, "prior": c.tmpl["prior"], "residual": resid, "violation": viol,
             "contradiction": contradiction, "metric_support": metric_support, "after_onset": after, "logit": S}
    return float(min(CONF_CAP, max(0.02, stats.sigmoid(S)))), parts


def _quality(c: Cand, kinds: set[str], rel: float) -> tuple[float, str]:
    f = c.f
    size = min(1.0, f.get("exposed_n", 0) / 150)
    control = min(1.0, 0.4 + f.get("unexposed_n", 0) / 60) if f.get("has_control") else 0.2
    if f.get("attribution") is not None and f.get("adj_vs"):
        control = min(1.0, control + 0.1)
    diversity = len(kinds) / 4
    q = 0.3 * size + 0.3 * control + 0.2 * diversity + 0.2 * rel
    return round(q, 3), ("high" if q >= 0.7 else "medium" if q >= 0.45 else "low")


def _evidence_items(ctx: Ctx, issue, c: Cand, kpi_label: str, onset, tm: dict, p0: float) -> list[dict]:
    f = c.f
    ev: list[dict] = []
    frm = str(c.start.date()) if c.start is not None else None

    def add(relation, kind, summary, weight, payload=None, **refs):
        ev.append({"relation": relation, "kind": kind, "summary": summary, "weight": round(weight, 3), "payload": payload or {}, **refs})

    for kind, obj in c.anchors:
        ts = obj.start_at if kind == "event" else obj.deployed_at
        lag = (onset - pd.Timestamp(ts).normalize()).days
        title = obj.title if kind == "event" else f"{obj.component} {obj.version}"
        if c.f.get("after_onset"):
            add("contradicts", kind, f"{title} started {pd.Timestamp(ts):%d %b %H:%M}, {abs(lag)} day(s) AFTER the issue onset ({onset:%d %b}); it cannot have caused the initial rise.", 0.9,
                {"timestamp": str(ts), "lag_days": lag}, **({"event_id": obj.id} if kind == "event" else {"release_id": obj.id}))
        else:
            add("supports", kind, f"{title} began {pd.Timestamp(ts):%d %b %H:%M}, {lag} day(s) before the issue onset ({onset:%d %b}).", 0.6,
                {"timestamp": str(ts), "lag_days": lag}, **({"event_id": obj.id} if kind == "event" else {"release_id": obj.id}))
    if f.get("exposed_n", 0) > 0:
        scope_desc = _scope_text(c.scope)
        add("supports", "statistic",
            f"{kpi_label} for {scope_desc} since the change is {f['rate_exposed']:.1%} ({f['exposed_k']}/{f['exposed_n']}); baseline for the same group was {f['p0_exposed']:.1%}.",
            min(1.0, f["coverage"]), {"frame": c.f["kpi"], "where": c.scope, "from": str(c.start.date()) if c.start is not None else None, "period": "post",
                                      "onset": str(onset.date()), "n": f["exposed_n"], "k": f["exposed_k"]})
        if f.get("unexposed_n", 0) >= 10:
            add("supports" if f["rate_unexposed"] < 0.5 * f["rate_exposed"] else "context", "statistic",
                f"All other units show {f['rate_unexposed']:.1%} ({f['unexposed_k']}/{f['unexposed_n']}) over the same period (contrast z={f['z_contrast']:.1f}).",
                0.5, {"frame": c.f["kpi"], "where": {"not": c.scope}, "from": frm, "onset": str(onset.date()), "period": "post", "n": f["unexposed_n"], "k": f["unexposed_k"]})
        if f.get("adj_vs"):
            add("supports" if (f.get("attribution") or 0) >= 0.5 else "contradicts", "statistic",
                f"After conditioning on the competing explanation \"{f['adj_vs']}\", {f['attribution']:.0%} of the exposed excess remains attributable to this factor (adjusted rate difference {f['adj_rd']:+.1%}).",
                abs((f.get('attribution') or 0) - 0.5), {"adjusted_rd": f["adj_rd"], "attribution": f["attribution"], "competitor": f["adj_vs"], "detail": f.get("adj_detail")})
        if f.get("residual", 0) > 0.15:
            add("contradicts", "statistic",
                f"{f['residual']:.0%} of the total excess occurs outside this group (units outside scope: {f['rate_unexposed']:.1%} vs {f['p0_unexposed']:.1%} baseline, z={f['z_unexposed']:.1f}), so this cause does not explain everything.",
                f["residual"], {"frame": c.f["kpi"], "where": {"not": c.scope}, "from": frm, "onset": str(onset.date()), "period": "post", "n": f["unexposed_n"], "k": f["unexposed_k"]})
        for d in f.get("dead_subgroups", [])[:2]:
            add("contradicts", "statistic",
                f"{d['share']:.0%} of the exposed units ({DIM_LABEL.get(d['dim'], d['dim'])} = {d['value']}) show no meaningful excess ({d['rate']:.1%}, {d['k']}/{d['n']}); exposure alone is not sufficient.",
                d["share"], {"frame": c.f["kpi"], "where": {**c.scope, d["dim"]: d["value"]}, "from": frm, "onset": str(onset.date()), "period": "post", "n": d["n"], "k": d["k"]})
        if not f.get("has_control"):
            add("context", "statistic", "No concurrent unexposed group exists (the change applied to every unit), so only before/after timing is available: correlation cannot be separated from coincident changes.", 0.4)
    if c.metric is not None:
        label = c.metric["label"]
        if c.metric_flat:
            add("contradicts", "metric", f"Direct measurement of {label} shows no elevation in any entity (max z={c.metric.get('max_z', 0):.1f}); this mechanism is not visible in the data.", 0.9,
                {"metric": c.metric["name"]})
        else:
            for ent, v in sorted(c.metric["hot"].items(), key=lambda kv: -kv[1]["z"])[:3]:
                add("supports", "metric", f"{label} for {ent} averaged {v['mean_post']:.1f} versus a baseline of {v['mean_base']:.1f} (z={v['z']:.1f}).", min(1.0, v["z"] / 6),
                    {"metric": c.metric["name"], "entity": ent, "z": v["z"], "signal_ids": v["signal_ids"]}, signal_id=v["signal_ids"][0] if v["signal_ids"] else None)
            for ent, v in c.metric["entities"].items():
                if ent not in c.metric["hot"] and v["z"] < 1.0 and len(c.metric["hot"]) and c.f.get("unexposed_n", 0) > 0:
                    add("context", "metric", f"{label} for {ent} is within its normal range (z={v['z']:.1f}).", 0.2, {"metric": c.metric["name"], "entity": ent})
                    break
    if tm["lift"] > 0.05 and tm["sample"]:
        add("supports", "complaint_sample",
            f"{tm['post']} complaint(s) since onset mention this mechanism ({tm['m_post']:.0%} of the issue's complaints vs {tm['m_base']:.0%} at baseline); e.g. \"{tm['sample'][0][1][:110]}\"", min(1.0, tm["lift"] / 0.25),
            {"terms": tm["terms"], "signal_ids": [s[0] for s in tm["sample"]]}, signal_id=tm["sample"][0][0])
    for x in f.get("conflicts", []):
        add("contradicts", "conflict", x["summary"], x["weight"], x["payload"], event_id=x.get("event_id"))
    return ev


def _conflicting_reports(ctx: Ctx, c: Cand, f_stats: dict) -> list[dict]:
    """Injected source reports that contradict our own measurements (reliability-weighted, never silently trusted)."""
    out = []
    names = {str(x).lower() for v in c.scope.values() for x in (v if isinstance(v, list) else [v])}
    for ev in ctx.view.events():
        a = ev.attributes or {}
        if ev.event_type != "partner_report" or not a.get("entity") or str(a["entity"]).lower() not in names:
            continue
        measured = 1 - f_stats.get("rate_exposed", 0)
        claim = float(a.get("claimed_on_time_rate", 0))
        if claim - measured > 0.2:
            out.append({"summary": f"{ev.title}: the source claims {claim:.0%} on-time performance, but transaction records show {measured:.0%} (reliability {ev.reliability:.2f} vs 0.98). "
                                   "Treated as a conflicting report: our measurement is preferred and the discrepancy should be reconciled.",
                        "weight": float(ev.reliability or 0.5), "payload": {"claimed": claim, "measured": measured, "source_reliability": ev.reliability}, "event_id": ev.id})
    return out


def run(ctx: Ctx, issue_id: int) -> AgentResult:
    db = ctx.db
    issue = db.get(DetectedIssue, issue_id)
    kpi_code, kpi_label = KPI_BY_ASPECT.get(issue.aspect, (None, None))
    iteration = issue.iteration
    if kpi_code is None:
        return AgentResult(output={"hypotheses": []}, reasoning="No structured KPI is mapped to this issue category; root-cause statistics need transaction, telemetry or release data.", status="succeeded")
    f = ctx.view.kpi_frame(kpi_code).copy()
    if f.empty:
        return AgentResult(output={"hypotheses": []}, reasoning="Structured KPI data is not available.", status="succeeded")
    onset = pd.Timestamp(issue.onset_at).normalize() if issue.onset_at else pd.Timestamp(ctx.view.w.recent_start)
    base_end = pd.Timestamp(ctx.view.w.baseline_end)
    pre, post = f["date"] < base_end, f["date"] >= onset
    p0 = f.loc[pre, "k"].sum() / max(f.loc[pre, "n"].sum(), 1)
    tot_excess = float(f.loc[post, "k"].sum() - p0 * f.loc[post, "n"].sum())
    cands = _build_candidates(ctx, issue, f, onset)
    for c in cands:
        c.f["kpi"] = kpi_code
    live = [c for c in cands if c.mask is not None and c.mask.any()]
    # refine release hypotheses whose effect is confined to a sub-population
    for c in [x for x in live if x.kind == "release"]:
        probe = _evaluate(f, c, onset, base_end, p0, [], tot_excess)
        if probe.get("violation", 0) >= 0.3:
            _refine(f, c, onset, p0, [x.mask for x in live if x is not c])
    for c in cands:
        c.f.update(_evaluate(f, c, onset, base_end, p0, live, tot_excess))
        c.f["kpi"] = kpi_code
    for c in cands:
        c.f["conflicts"] = _conflicting_reports(ctx, c, c.f)
        c.f["conflict_weight"] = max([x["weight"] for x in c.f["conflicts"]], default=0.0)
    results = []
    failed = {}
    for iv in db.scalars(select(Intervention).where(Intervention.issue_id == issue.id, Intervention.verification_status == "not_recovered", Intervention.status == "executed")):
        for ct in INTERVENTIONS.get(iv.intervention_type, {}).get("addresses", {}):
            failed[ct] = iv
    for c in cands:
        tm = _text_mentions(ctx, issue, c, onset)
        lag = (onset - c.start).days if c.start is not None else None
        conf, parts = _score(c, tm, lag)
        c.f["after_onset"] = parts.get("after_onset", False)
        iv = failed.get(c.cause_type)
        if iv is not None and not c.no_data:
            conf = max(0.02, conf * 0.35)
            c.f.setdefault("conflicts", []).append({"summary": f"Intervention \"{iv.title}\" targeting this cause was executed on {pd.Timestamp(iv.executed_at):%d %b} but the {kpi_label.lower()} did not recover; the hypothesis is weakened by interventional evidence.",
                                                    "weight": 1.0, "payload": {"intervention_id": iv.id, "verdict": "not_recovered"}})
        items = _evidence_items(ctx, issue, c, kpi_label, onset, tm, p0)
        kinds = {e["kind"] if e["kind"] not in ("event", "release") else "anchor" for e in items if e["relation"] == "supports"}
        rel = float(np.mean([getattr(o, "reliability", 0.9) or 0.9 for _, o in c.anchors] + [0.98]))
        q, qlabel = _quality(c, kinds, rel)
        results.append({"c": c, "conf": conf, "parts": parts, "tm": tm, "items": items, "q": q, "ql": qlabel})
    # merge hypotheses that share a cause type: keep the strongest, fold the rest in as context
    best: dict[str, dict] = {}
    for r in sorted(results, key=lambda r: -r["conf"]):
        ct = r["c"].cause_type
        if ct not in best:
            best[ct] = r
            r["merged"] = []
        else:
            best[ct]["merged"].append(r)
    ranked = sorted(best.values(), key=lambda r: -r["conf"])[:6]
    # persist
    db.execute(update(RootCauseHypothesis).where(RootCauseHypothesis.issue_id == issue.id, RootCauseHypothesis.is_current.is_(True)).values(is_current=False))
    rand_z = float(issue.stats["kpi"]["z"]) if issue.stats and issue.stats.get("kpi") else None
    out_rows = []
    for rank, r in enumerate(ranked, start=1):
        c, conf = r["c"], r["conf"]
        top_status = "leading" if rank == 1 and conf >= 0.6 else None
        if c.no_data:
            status = "insufficient_data"
        elif r["parts"].get("contradiction", 0) >= 1.0 and conf < 0.15:
            status = "refuted"
        elif top_status:
            status = top_status
        elif conf >= 0.35:
            status = "plausible"
        else:
            status = "unlikely"
        if c.f.get("has_control") and c.f.get("attribution") is not None and c.f.get("adj_vs"):
            claim = "Adjusted contrast against a concurrent control group supports a causal reading; causation is not proven."
        elif c.f.get("has_control"):
            claim = "Contrast with unexposed units supports association; confounders may remain, causation is not proven."
        elif c.no_data:
            claim = "No diagnostic data - this explanation cannot be tested yet."
        else:
            claim = "Timing correlation only (no concurrent control group); causation cannot be inferred."
        others = [x for x in ranked if x is not r]
        alternatives = [{"title": o["c"].title, "cause_type": o["c"].cause_type, "confidence": round(o["conf"], 3)} for o in others[:3]]
        if rand_z is not None:
            alternatives.append({"title": "Random variation / seasonality", "cause_type": "noise", "confidence": 0.01,
                                 "note": f"Rejected: the KPI shift is z={rand_z:.1f} against the historical baseline."})
        needed = list(c.tmpl.get("data_needed", []))
        if c.f.get("attribution") is None and not c.no_data:
            needed.append("A control group not exposed to this change, or a staggered rollout, to separate it from coincident changes")
        statement = (f"{c.title} may be driving the rise in {kpi_label.lower()}" if not c.no_data else
                     f"{CAUSE_LABEL[c.cause_type]} cannot be evaluated because no diagnostic data is connected")
        h = RootCauseHypothesis(issue_id=issue.id, iteration=iteration, is_current=True, rank=rank, title=c.title, cause_type=c.cause_type, statement=statement,
                                confidence=round(conf, 3), evidence_quality=r["q"], quality_label=r["ql"], status=status, causal_claim=claim,
                                alternatives=alternatives, additional_data_needed=needed[:4],
                                features={k: (None if (isinstance(v, float) and (math.isnan(v) or math.isinf(v))) else v) for k, v in {**c.f, **{"score": r["parts"]}}.items()
                                          if k not in ("conflicts", "adj_detail", "kpi")} | {"kpi": kpi_code, "as_of": ctx.now.isoformat()},
                                scope=c.scope)
        db.add(h)
        db.flush()
        for e in r["items"] + [{"relation": "context", "kind": "event", "summary": f"Related change folded into this hypothesis: {m['c'].title}", "weight": 0.2, "payload": {},
                                **({"event_id": m['c'].anchors[0][1].id} if m["c"].anchors and m["c"].anchors[0][0] == "event" else
                                   {"release_id": m['c'].anchors[0][1].id} if m["c"].anchors and m["c"].anchors[0][0] == "release" else {})} for m in r["merged"]]:
            db.add(HypothesisEvidence(hypothesis_id=h.id, relation=e["relation"], kind=e["kind"], summary=e["summary"], weight=e["weight"], payload=e["payload"],
                                      signal_id=e.get("signal_id"), event_id=e.get("event_id"), release_id=e.get("release_id")))
        out_rows.append({"id": h.id, "rank": rank, "title": c.title, "cause_type": c.cause_type, "confidence": round(conf, 3), "status": status, "quality": r["ql"]})
    # deterministic + optional LLM narrative for the top hypotheses
    db.flush()
    for row in out_rows[:3]:
        h = db.get(RootCauseHypothesis, row["id"])
        sup = [e for e in h.evidence if e.relation == "supports"][:3]
        con = [e for e in h.evidence if e.relation == "contradicts"][:2]
        facts = {"hypothesis": h.title, "confidence": h.confidence, "quality": h.quality_label, "causal_claim": h.causal_claim,
                 "supporting": [{"id": f"E{e.id}", "text": e.summary} for e in sup], "contradicting": [{"id": f"E{e.id}", "text": e.summary} for e in con]}
        fallback = (f"{h.title}: confidence {h.confidence:.0%} with {h.quality_label} evidence quality. " +
                    (f"Supporting: {sup[0].summary} " if sup else "") + (f"Against: {con[0].summary} " if con else "") + h.causal_claim)
        h.narrative = ctx.llm.explain("root_cause_summary", facts, fallback)
    top = ranked[0] if ranked else None
    reasoning = (f"Evaluated {len(cands)} candidate cause(s) from events, releases, metrics and mechanism templates against {kpi_label.lower()} "
                 f"(onset {onset:%d %b}, baseline {p0:.1%}); " + (f"leading hypothesis: \"{top['c'].title}\" at {top['conf']:.0%} confidence, {top['ql']} evidence quality." if top else "no hypothesis qualified.") +
                 " Confidence reflects evidence strength and is capped below certainty.")
    return AgentResult(output={"hypotheses": out_rows, "candidates_evaluated": len(cands), "kpi": kpi_code, "baseline_rate": p0, "total_excess": tot_excess},
                       reasoning=reasoning, inputs={"issue": issue.code, "onset": str(onset.date()), "kpi": kpi_code})
