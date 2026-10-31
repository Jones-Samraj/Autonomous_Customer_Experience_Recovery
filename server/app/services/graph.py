"""Evidence graph linking signals, issues, segments, operational events, hypotheses and interventions (NetworkX)."""
from __future__ import annotations

import networkx as nx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.common import inv_state
from app.models import (DetectedIssue, Intervention, IssueCluster, OperationalEvent, ProductRelease, RootCauseHypothesis)


def build(db: Session, issue_id: int) -> dict:
    issue = db.get(DetectedIssue, issue_id)
    G = nx.DiGraph()
    iid = f"issue:{issue.id}"
    G.add_node(iid, type="issue", label=issue.code, title=issue.title, severity=issue.severity, confidence=issue.detection_confidence, support=issue.support_count)
    for c in db.scalars(select(IssueCluster).where(IssueCluster.issue_id == issue_id).order_by(IssueCluster.size.desc()).limit(6)):
        nid = f"cluster:{c.id}"
        G.add_node(nid, type="signal_group", label=f"{c.size} complaints", title=c.label, size=c.size, z=c.z_score, terms=c.top_terms)
        G.add_edge(nid, iid, relation="reports", weight=min(1.0, c.size / 40))
    seg = inv_state(db, issue_id).get("segmentation") or {}
    for i, s in enumerate((seg.get("segments") or [])[:5]):
        nid = f"segment:{i}"
        G.add_node(nid, type="segment", label=f"{s['label']}: {s['value']}", title=s["pattern"], rate=s["rate"], lift=s["lift"], affected=s["affected"])
        G.add_edge(iid, nid, relation="concentrated_in", weight=min(1.0, s["rate"]))
    hyps = list(db.scalars(select(RootCauseHypothesis).where(RootCauseHypothesis.issue_id == issue_id, RootCauseHypothesis.is_current.is_(True)).order_by(RootCauseHypothesis.rank)))
    for h in hyps:
        hid = f"hyp:{h.id}"
        G.add_node(hid, type="hypothesis", label=h.title[:60], title=h.title, confidence=h.confidence, status=h.status, quality=h.quality_label, cause_type=h.cause_type,
                   causal_claim=h.causal_claim)
        G.add_edge(hid, iid, relation="explains", weight=h.confidence)
        pref = {"event": 0, "release": 0, "metric": 1, "statistic": 2}  # keep the graph readable: the most informative few items
        sup = sorted([e for e in h.evidence if e.relation == "supports" and e.kind != "complaint_sample"], key=lambda e: (pref.get(e.kind, 3), -e.weight))[:2 if h.rank == 1 else 1]
        con = sorted([e for e in h.evidence if e.relation == "contradicts"], key=lambda e: -e.weight)[:1]
        for e in sup + con:
            if e.event_id:
                ev = db.get(OperationalEvent, e.event_id)
                nid, typ, label = f"event:{e.event_id}", "event", ev.title[:50]
            elif e.release_id:
                rel = db.get(ProductRelease, e.release_id)
                nid, typ, label = f"release:{e.release_id}", "release", f"{rel.component} {rel.version}"
            else:
                nid, typ, label = f"ev:{e.id}", ("metric" if e.kind == "metric" else "statistic"), e.summary[:50]
            if nid not in G:
                G.add_node(nid, type=typ, label=label, title=e.summary, kind=e.kind)
            G.add_edge(nid, hid, relation=e.relation, weight=e.weight, summary=e.summary)
        samples = [e for e in h.evidence if e.kind == "complaint_sample"]
        if h.rank == 1 and samples and (samples[0].payload or {}).get("signal_ids"):
            nid = f"sample:{h.id}"
            G.add_node(nid, type="signal_group", label=f"{len((samples[0].payload or {}).get('signal_ids', []))} sampled complaints", title=samples[0].summary,
                       signal_ids=(samples[0].payload or {}).get("signal_ids"))
            G.add_edge(nid, hid, relation="supports", weight=samples[0].weight)
    for iv in db.scalars(select(Intervention).where(Intervention.issue_id == issue_id, Intervention.iteration == issue.iteration, Intervention.superseded.is_(False),
                                                    Intervention.role == "root_cause_fix").order_by(Intervention.rank).limit(3)):
        nid = f"int:{iv.id}"
        G.add_node(nid, type="intervention", label=iv.title[:55], title=iv.rationale, status=iv.status, recommended=iv.is_recommended, utility=iv.utility, code=iv.code)
        if iv.target_hypothesis_id and f"hyp:{iv.target_hypothesis_id}" in G:
            G.add_edge(nid, f"hyp:{iv.target_hypothesis_id}", relation="addresses", weight=iv.expected_impact or 0.0)
    deg = dict(G.degree())
    nodes = [{"id": n, **{k: v for k, v in d.items()}, "degree": deg[n]} for n, d in G.nodes(data=True)]
    edges = [{"source": u, "target": v, **d} for u, v, d in G.edges(data=True)]
    return {"nodes": nodes, "edges": edges, "issue": issue.code}
