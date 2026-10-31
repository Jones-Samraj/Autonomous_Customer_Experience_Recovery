"""Benchmark ground truth. Written to ``data/benchmark`` and read ONLY by the evaluation service.

The investigation agents never import or read this module or its output file.
"""
from __future__ import annotations

from app.agents.domain import BEST_FOR_CAUSE, CAUSE_LABEL

CATEGORY = {"delivery": "Delivery Delays", "payment": "Payment Failures", "app": "Mobile App Crashes",
            "product_quality": "Product Quality", "refund": "Refund Processing Delays"}


def build_ground_truth(state: dict) -> dict:
    issues, decoys = [], []
    for f in state["factors"]:
        if f.get("truth") and f.get("issue"):
            issues.append({"id": f"GT-{f['issue'].upper()}", "aspect": f["issue"], "category": CATEGORY[f["issue"]], "onset_at": f["start"],
                           "cause_type": f["cause_type"], "cause_label": f["label"], "affected_scope": f.get("scope", {}),
                           "acceptable_interventions": BEST_FOR_CAUSE.get(f["cause_type"], [])})
        elif not f.get("truth"):
            decoys.append({"id": f["id"], "cause_type": f["cause_type"], "label": f["label"], "issue": f.get("issue"),
                           "note": "real but minor/non-causal" if f.get("target") else "no effect on customer KPIs"})
    return {
        "simulated": True,
        "description": "Ground truth for the simulated e-commerce benchmark. Hidden from the investigation agents.",
        "issues": issues,
        "non_issues": [{"aspect": "pricing", "note": "steady baseline with a two-day blip"},
                       {"aspect": "packaging", "note": "one-day social burst, not sustained"}],
        "decoy_causes": decoys,
        "cause_labels": {k: CAUSE_LABEL[k] for k in {i["cause_type"] for i in issues} if k in CAUSE_LABEL},
    }
