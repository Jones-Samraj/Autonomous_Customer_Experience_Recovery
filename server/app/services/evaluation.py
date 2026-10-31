"""AI Evaluation Center: scores the platform against the hidden benchmark ground truth.

This is the ONLY module (besides the world simulator) that reads ``data/benchmark/ground_truth.json``.
"""
from __future__ import annotations

import json
import threading
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.common import inv_state
from app.agents.context import Ctx
from app.core.config import get_settings
from app.models import (AgentExecutionHistory, ApprovalRequest, DetectedIssue, Intervention, Investigation, RootCauseHypothesis)
from app.services.evidence import groundedness

_LAT: dict[str, deque] = defaultdict(lambda: deque(maxlen=500))
_LOCK = threading.Lock()


def record_latency(route: str, ms: float) -> None:
    with _LOCK:
        _LAT[route].append(ms)


def latency_summary() -> dict:
    with _LOCK:
        allv = [x for v in _LAT.values() for x in v]
        per = {r: {"count": len(v), "p50": float(np.percentile(v, 50)), "p95": float(np.percentile(v, 95))} for r, v in _LAT.items() if v}
    if not allv:
        return {"count": 0, "p50": None, "p95": None, "routes": []}
    top = sorted(per.items(), key=lambda kv: -kv[1]["p95"])[:8]
    return {"count": len(allv), "p50": float(np.percentile(allv, 50)), "p95": float(np.percentile(allv, 95)),
            "routes": [{"route": r, **v} for r, v in top]}


def load_truth() -> dict | None:
    p = Path(get_settings().data_dir) / "benchmark" / "ground_truth.json"
    return json.loads(p.read_text()) if p.exists() else None


def _first_iteration_hypotheses(db: Session, issue_id: int) -> list[RootCauseHypothesis]:
    first = db.scalar(select(func.min(RootCauseHypothesis.iteration)).where(RootCauseHypothesis.issue_id == issue_id))
    if first is None:
        return []
    return list(db.scalars(select(RootCauseHypothesis).where(RootCauseHypothesis.issue_id == issue_id, RootCauseHypothesis.iteration == first).order_by(RootCauseHypothesis.rank)))


def compute(db: Session) -> dict:
    truth = load_truth()
    ctx = Ctx(db, "evaluation")
    issues = list(db.scalars(select(DetectedIssue)))
    confirmed = [i for i in issues if i.status not in ("watchlist", "superseded")]
    out: dict = {"benchmark_available": truth is not None, "simulated": True}
    per_issue = []
    if truth:
        gt = truth["issues"]
        matched, used = [], set()
        for g in gt:
            onset = datetime.fromisoformat(g["onset_at"])
            m = next((i for i in confirmed if i.aspect == g["aspect"] and i.id not in used and i.onset_at and abs((i.onset_at - onset).days) <= 4), None)
            if m:
                used.add(m.id)
            matched.append((g, m))
        tp = sum(1 for _, m in matched if m)
        fp = len([i for i in confirmed if i.id not in used])
        fn = len(gt) - tp
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        non = truth["non_issues"]
        fp_non = sum(1 for n in non if any(i.aspect == n["aspect"] for i in confirmed))
        out["detection"] = {"precision": precision, "recall": recall, "f1": (2 * precision * recall / (precision + recall)) if precision and recall else None,
                            "true_positives": tp, "false_positives": fp, "false_negatives": fn, "false_positive_rate": fp_non / len(non) if non else None,
                            "decoys_tested": len(non), "decoys_flagged_as_issues": fp_non,
                            "decoys_on_watchlist": sum(1 for n in non if any(i.aspect == n["aspect"] and i.status == "watchlist" for i in issues))}
        rr, top1, top3, corr_conf, wrong_conf, seg_scores, delays, cause_rows = [], 0, 0, [], [], [], [], []
        for g, m in matched:
            row = {"ground_truth": g["id"], "aspect": g["aspect"], "category": g["category"], "detected": m.code if m else None,
                   "true_cause": g["cause_type"], "detected_rank_of_true_cause": None, "top_hypothesis": None, "top_confidence": None, "onset_error_days": None, "detection_delay_days": None}
            if m:
                row["onset_error_days"] = abs((m.onset_at - datetime.fromisoformat(g["onset_at"])).days)
                if m.first_detected_at:
                    d = (m.first_detected_at - datetime.fromisoformat(g["onset_at"])).days
                    row["detection_delay_days"] = d
                    delays.append(d)
                hyps = _first_iteration_hypotheses(db, m.id)
                real = [h for h in hyps if h.status != "insufficient_data"]
                rank = next((n for n, h in enumerate(real, 1) if h.cause_type == g["cause_type"]), None)
                row["detected_rank_of_true_cause"] = rank
                if real:
                    row["top_hypothesis"], row["top_confidence"] = real[0].title, real[0].confidence
                    (corr_conf if real[0].cause_type == g["cause_type"] else wrong_conf).append(real[0].confidence)
                rr.append(1 / rank if rank else 0.0)
                top1 += 1 if rank == 1 else 0
                top3 += 1 if rank and rank <= 3 else 0
                top_iv = db.scalars(select(Intervention).where(Intervention.issue_id == m.id, Intervention.is_recommended.is_(True), Intervention.role == "root_cause_fix").order_by(Intervention.iteration, Intervention.rank)).first()
                row["recommended_intervention"] = top_iv.intervention_type if top_iv else None
                row["recommendation_acceptable"] = bool(top_iv and top_iv.intervention_type in g["acceptable_interventions"])
                seg = (inv_state(db, m.id).get("segmentation") or {}).get("segments", [])[:6]
                found = {(s["dimension"], s["value"]) for s in seg}
                gt_pairs = {(k, str(x)) for k, v in g["affected_scope"].items() for x in (v if isinstance(v, list) else [v])}
                if gt_pairs:
                    hit = len(gt_pairs & found)
                    rec = hit / len(gt_pairs)
                    prec = hit / len(found) if found else 0.0
                    seg_scores.append({"recall": rec, "precision": prec})
                    row["segmentation"] = {"expected": sorted(f"{a}={b}" for a, b in gt_pairs), "found": sorted(f"{a}={b}" for a, b in found), "recall": rec}
            cause_rows.append(row)
        n = len(gt)
        out["root_cause"] = {"top1_accuracy": top1 / n if n else None, "top3_recall": top3 / n if n else None, "mean_reciprocal_rank": float(np.mean(rr)) if rr else None,
                             "mean_confidence_when_correct": float(np.mean(corr_conf)) if corr_conf else None,
                             "mean_confidence_when_wrong": float(np.mean(wrong_conf)) if wrong_conf else None}
        out["segmentation"] = {"recall": float(np.mean([s["recall"] for s in seg_scores])) if seg_scores else None,
                               "precision_top6": float(np.mean([s["precision"] for s in seg_scores])) if seg_scores else None}
        out["time_to_detect"] = {"mean_days_after_onset": float(np.mean(delays)) if delays else None}
        per_issue = cause_rows
        ok_rec = [r for r in cause_rows if r.get("recommended_intervention")]
        out["recommendation_alignment"] = {"acceptable_share": (sum(1 for r in ok_rec if r["recommendation_acceptable"]) / len(ok_rec)) if ok_rec else None}
    out["per_issue"] = per_issue
    g = groundedness(db, ctx.view)
    out["groundedness"] = {"ratio": g["ratio"], "checked": g["checked"], "grounded": g["grounded"], "ungrounded": g["ungrounded"][:5]}
    decided = db.execute(select(ApprovalRequest.status, func.count()).where(ApprovalRequest.status.in_(["approved", "rejected"]), ApprovalRequest.decided_by.is_not(None)).group_by(ApprovalRequest.status)).all()
    dd = dict(decided)
    tot = sum(dd.values())
    out["interventions"] = {"human_decisions": tot, "approved": dd.get("approved", 0), "rejected": dd.get("rejected", 0), "acceptance_rate": (dd.get("approved", 0) / tot) if tot else None,
                            "executed": db.scalar(select(func.count()).select_from(Intervention).where(Intervention.status == "executed")) or 0,
                            "failed_executions": db.scalar(select(func.count()).select_from(Intervention).where(Intervention.status == "failed")) or 0}
    invs = list(db.scalars(select(Investigation)))
    done = [i for i in invs if i.status in ("awaiting_approval", "monitoring", "resolved", "completed", "reopened")]
    hist = db.execute(select(AgentExecutionHistory.status, func.count()).where(AgentExecutionHistory.agent != "Orchestrator (Supervisor)").group_by(AgentExecutionHistory.status)).all()
    hd = dict(hist)
    out["task_completion"] = {"investigations": len(invs), "completed": len(done), "completion_rate": (len(done) / len(invs)) if invs else None,
                              "agent_runs": sum(hd.values()), "agent_success_rate": (hd.get("succeeded", 0) / sum(hd.values())) if hd else None}
    out["api_latency"] = latency_summary()
    agent_lat = db.execute(select(AgentExecutionHistory.agent, func.avg(AgentExecutionHistory.duration_ms), func.max(AgentExecutionHistory.duration_ms), func.count())
                           .where(AgentExecutionHistory.agent != "Orchestrator (Supervisor)").group_by(AgentExecutionHistory.agent)).all()
    out["agent_latency"] = [{"agent": a, "avg_ms": float(av or 0), "max_ms": int(mx or 0), "runs": int(c)} for a, av, mx, c in agent_lat]
    tok = db.execute(select(func.coalesce(func.sum(AgentExecutionHistory.llm_tokens_in), 0), func.coalesce(func.sum(AgentExecutionHistory.llm_tokens_out), 0),
                            func.coalesce(func.sum(AgentExecutionHistory.llm_cost_usd), 0.0))).one()
    out["ai_cost"] = {"tokens_in": int(tok[0]), "tokens_out": int(tok[1]), "estimated_usd": float(tok[2]), "llm_provider": get_settings().llm_provider,
                      "per_investigation_usd": float(tok[2]) / len(invs) if invs else 0.0,
                      "note": "Statistical agents run locally at zero marginal cost; cost is incurred only when an LLM provider is configured for explanations."}
    ver = [r for h in db.scalars(select(AgentExecutionHistory).where(AgentExecutionHistory.agent == "Verification & Learning Agent", AgentExecutionHistory.status == "succeeded"))
           for r in (h.output_summary or {}).get("results", [])]
    latest: dict[int, dict] = {}
    for r in ver:
        latest[r["intervention_id"]] = r
    rec = [r for r in latest.values() if r["verdict"] == "recovered"]
    out["recovery"] = {"verified_interventions": len([r for r in latest.values() if r["verdict"] in ("recovered", "not_recovered", "partial")]),
                       "recovered": len(rec), "not_recovered": len([r for r in latest.values() if r["verdict"] == "not_recovered"]),
                       "success_rate": (len(rec) / len([r for r in latest.values() if r["verdict"] in ("recovered", "not_recovered")])) if any(r["verdict"] in ("recovered", "not_recovered") for r in latest.values()) else None,
                       "mean_recovery_days": float(np.mean([r["post"]["days"] for r in rec])) if rec else None,
                       "mean_kpi_improvement": float(np.mean([r["relative_improvement"] for r in rec])) if rec else None,
                       "details": [{"intervention": r["intervention"], "verdict": r["verdict"], "pre": r["pre"].get("rate"), "post": r["post"].get("rate"), "kpi": r["kpi"]} for r in latest.values()]}
    return out
