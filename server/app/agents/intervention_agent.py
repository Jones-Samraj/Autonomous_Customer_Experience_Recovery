"""Agent 6 - Intervention Planning.

Candidate interventions are drawn from the catalogue and scored against the *current* hypothesis confidences, so the ranking
moves whenever the evidence moves. Consequential actions are never executed here - they are submitted for human approval.
"""
from __future__ import annotations

from sqlalchemy import select

from app.agents.context import AgentResult, Ctx
from app.agents.domain import INTERVENTIONS
from app.agents.impact_agent import current_estimates
from app.db import utcnow
from app.models import ApprovalRequest, DetectedIssue, Intervention, InterventionComparison, RootCauseHypothesis

WEIGHTS = {"expected_impact": 0.30, "customer_benefit": 0.15, "confidence": 0.15, "feasibility": 0.10, "reversibility": 0.10,
           "business_risk": -0.10, "cost": -0.07, "execution_time": -0.03}


def _supersede(db, issue_id: int, iteration: int) -> int:
    n = 0
    for iv in db.scalars(select(Intervention).where(Intervention.issue_id == issue_id, Intervention.superseded.is_(False),
                                                    Intervention.status.in_(["proposed", "pending_approval", "approved"]))):
        iv.superseded = True
        iv.status = "superseded" if iv.status != "approved" else iv.status
        for ar in db.scalars(select(ApprovalRequest).where(ApprovalRequest.intervention_id == iv.id, ApprovalRequest.status == "pending")):
            ar.status, ar.comment, ar.decided_at = "superseded", f"Superseded by re-investigation (iteration {iteration})", utcnow()
        n += 1
    return n


def _fmt_inr(x: float) -> str:
    return f"INR {x:,.0f}"


def run(ctx: Ctx, issue_id: int) -> AgentResult:
    db = ctx.db
    issue = db.get(DetectedIssue, issue_id)
    hyps = list(db.scalars(select(RootCauseHypothesis).where(RootCauseHypothesis.issue_id == issue_id, RootCauseHypothesis.is_current.is_(True)).order_by(RootCauseHypothesis.rank)))
    usable = [h for h in hyps if h.status not in ("insufficient_data",) and h.confidence >= 0.05][:5]
    total_conf = sum(h.confidence for h in usable) or 1.0
    weight = {h.id: h.confidence / total_conf for h in usable}
    impact = current_estimates(db, issue_id)
    measured = (impact.get("affected_customers_measured").value if impact.get("affected_customers_measured") else 0) or 0
    nxt = (impact.get("affected_customers_next_7d").value if impact.get("affected_customers_next_7d") else 0) or 0
    n_aff = max(1.0, measured + nxt)
    iteration = issue.iteration
    superseded = _supersede(db, issue_id, iteration)

    already = {iv.intervention_type for iv in db.scalars(select(Intervention).where(Intervention.issue_id == issue_id, Intervention.status == "executed"))}
    cands = []
    for itype, spec in INTERVENTIONS.items():
        if itype in already:
            continue  # executed earlier and awaiting / failing verification: do not propose the same action twice
        contrib = [(h, spec["addresses"].get(h.cause_type, 0.0)) for h in usable]
        eff_mass = sum(weight[h.id] * e for h, e in contrib)
        if spec["role"] == "root_cause_fix" and eff_mass < 0.05:
            continue
        if spec["role"] == "root_cause_fix":
            expected_impact = eff_mass
            addressed = [(h, e) for h, e in contrib if e > 0]
            conf = sum(weight[h.id] * h.confidence * e for h, e in addressed) / max(sum(weight[h.id] * e for h, e in addressed), 1e-9)
            target = max(addressed, key=lambda x: weight[x[0].id] * x[1])[0]
            benefit = expected_impact * n_aff
        elif spec["role"] == "customer_mitigation":
            expected_impact = (1 - spec.get("complaint_mult", 0.9)) * 0.5
            conf, target = 0.7, (usable[0] if usable else None)
            benefit = n_aff * (1 - spec.get("complaint_mult", 0.9)) * 0.8
        else:
            expected_impact, conf, target, benefit = 0.03, 0.9, (usable[0] if usable else None), 0.0
        units = n_aff
        cost = spec["cost_fixed"] + spec["cost_per_unit"] * units
        risk = min(0.95, spec["risk"] + (0.35 * (1 - conf) if spec["role"] == "root_cause_fix" else 0.0))
        cands.append({"type": itype, "spec": spec, "impact": expected_impact, "benefit": benefit, "confidence": min(0.95, conf), "cost": cost, "hours": spec["hours"],
                      "risk": risk, "feasibility": spec["feasibility"], "reversibility": spec["reversibility"], "target": target,
                      "addressed": [(h.title, round(weight[h.id], 3), e) for h, e in contrib if e > 0]})
    max_b = max((c["benefit"] for c in cands), default=1.0) or 1.0
    max_c = max((c["cost"] for c in cands), default=1.0) or 1.0
    for c in cands:
        norm = {"expected_impact": c["impact"], "customer_benefit": c["benefit"] / max_b, "confidence": c["confidence"], "feasibility": c["feasibility"],
                "reversibility": c["reversibility"], "business_risk": c["risk"], "cost": c["cost"] / max_c, "execution_time": min(1.0, c["hours"] / 72)}
        contrib = {k: WEIGHTS[k] * norm[k] for k in WEIGHTS}
        c["norm"], c["contrib"], c["utility"] = norm, contrib, sum(contrib.values())
    cands.sort(key=lambda c: -c["utility"])
    fixes = [c for c in cands if c["spec"]["role"] == "root_cause_fix"]
    mitig = [c for c in cands if c["spec"]["role"] == "customer_mitigation"]
    coord = [c for c in cands if c["spec"]["role"] == "coordination"]
    for group in (fixes, mitig, coord):  # utilities are only comparable within a role, so rank within the role
        for pos, c in enumerate(group, start=1):
            c["role_rank"] = pos
    package = [x for x in (fixes[:1] + mitig[:1] + [c for c in coord if c["type"] == "create_technical_incident"][:1]) if x]
    pkg_types = {c["type"] for c in package}

    db.flush()
    seq = db.query(Intervention).count()
    rows = []
    for c in cands:
        rank = c["role_rank"]
        seq += 1
        spec = c["spec"]
        needs = bool(spec["consequential"] or c["cost"] > ctx.s.approval_cost_threshold_inr)
        c["requires_approval"] = needs
        if c["type"] in pkg_types:
            if spec["role"] == "root_cause_fix" and len(fixes) > 1:
                alt = fixes[1]
                rationale = (f"Recommended: addresses \"{c['target'].title}\" (confidence {c['target'].confidence:.0%}) with expected impact {c['impact']:.0%} versus {alt['impact']:.0%} for "
                             f"\"{alt['spec']['title']}\"; "
                             f"cost {_fmt_inr(c['cost'])} vs {_fmt_inr(alt['cost'])}, risk {c['risk']:.0%} vs {alt['risk']:.0%}, reversibility {c['reversibility']:.0%} vs {alt['reversibility']:.0%}.")
            elif spec["role"] == "root_cause_fix":
                rationale = f"Recommended: the only root-cause action that addresses \"{c['target'].title}\" (confidence {c['target'].confidence:.0%}); expected impact {c['impact']:.0%}."
            elif spec["role"] == "customer_mitigation":
                rationale = f"Recommended alongside the fix: reduces customer harm while the root cause is being resolved (benefits ~{c['benefit']:.0f} customers at {_fmt_inr(c['cost'])}); it does not remove the root cause."
            else:
                rationale = "Recommended coordination step: creates an owned incident so the fix is tracked and time-boxed."
        else:
            reason = []
            if spec["role"] == "root_cause_fix" and fixes and fixes[0]["type"] != c["type"]:
                reason.append(f"expected impact {c['impact']:.0%} vs {fixes[0]['impact']:.0%} for the recommended action")
                if c["cost"] > fixes[0]["cost"]:
                    reason.append(f"higher cost ({_fmt_inr(c['cost'])})")
                if c["risk"] > fixes[0]["risk"]:
                    reason.append(f"higher business risk ({c['risk']:.0%})")
            rationale = "Not preferred: " + ("; ".join(reason) if reason else "lower overall utility than the recommended package") + "."
        c["rationale"] = rationale
        status = "proposed"
        iv = Intervention(code=f"INT-{seq:04d}", issue_id=issue_id, iteration=iteration, intervention_type=c["type"], title=spec["title"],
                          description=f"{spec['title']} - owner: {spec['department']}.", role=spec["role"],
                          params={"cause_types": [k for k in spec["addresses"]], "scope": c["target"].scope if c["target"] else {}, "department": spec["department"],
                                  "units": round(n_aff, 1), "change": spec.get("change"), "complaint_mult": spec.get("complaint_mult"), "aspect": issue.aspect,
                                  "amount_inr": round(c["cost"], 0)},
                          status=status, requires_approval=needs, is_consequential=bool(spec["consequential"]), expected_impact=round(c["impact"], 3),
                          cost_inr=round(c["cost"], 0), execution_hours=c["hours"], customer_benefit=int(c["benefit"]), business_risk=round(c["risk"], 3),
                          feasibility=c["feasibility"], confidence=round(c["confidence"], 3), reversibility=c["reversibility"], utility=round(c["utility"], 4), rank=rank,
                          is_recommended=c["type"] in pkg_types, rationale=rationale, target_hypothesis_id=c["target"].id if c["target"] else None)
        db.add(iv)
        db.flush()
        db.add(InterventionComparison(issue_id=issue_id, iteration=iteration, intervention_id=iv.id, rank=rank, utility=iv.utility,
                                      criteria={"normalised": {k: round(v, 3) for k, v in c["norm"].items()}, "weighted_contribution": {k: round(v, 4) for k, v in c["contrib"].items()},
                                                "weights": WEIGHTS, "addresses": c["addressed"]}, rationale=rationale))
        if iv.is_recommended:
            summary = {"cost_inr": iv.cost_inr, "expected_impact": iv.expected_impact, "business_risk": iv.business_risk, "reversibility": iv.reversibility,
                       "target_hypothesis": c["target"].title if c["target"] else None, "target_confidence": c["target"].confidence if c["target"] else None,
                       "evidence_quality": c["target"].quality_label if c["target"] else None, "iteration": iteration}
            if needs:
                iv.status = "pending_approval"
                db.add(ApprovalRequest(intervention_id=iv.id, status="pending", summary=summary))
            else:
                iv.status = "approved"
                iv.approved_at = utcnow()
                db.add(ApprovalRequest(intervention_id=iv.id, status="approved", decided_at=utcnow(), comment="Auto-approved by policy: non-consequential action", summary=summary))
        rows.append({"id": iv.id, "code": iv.code, "type": iv.intervention_type, "rank": rank, "utility": iv.utility, "recommended": iv.is_recommended, "status": iv.status,
                     "requires_approval": needs})
    db.flush()
    top = cands[0] if cands else None
    pkg_titles = "; ".join(c["spec"]["title"] for c in package)
    facts = {"issue": issue.title, "recommended_package": [c["spec"]["title"] for c in package],
             "top_rationale": package[0]["rationale"] if package else "", "leading_hypothesis": usable[0].title if usable else None}
    reasoning = ctx.llm.explain("intervention_plan_summary", facts,
                                f"Scored {len(cands)} candidate interventions against {len(usable)} live hypotheses (weights = normalised confidence). Recommended package: {pkg_titles}. "
                                + (package[0]["rationale"] if package else ""))
    return AgentResult(output={"interventions": rows, "recommended": [c["type"] for c in package], "superseded": superseded, "hypothesis_weights": {str(k): round(v, 3) for k, v in weight.items()}},
                       reasoning=reasoning, inputs={"issue": issue.code, "hypotheses_used": len(usable), "affected_customers": round(n_aff, 1)})
