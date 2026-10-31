"""Shared domain knowledge: cause taxonomy, hypothesis templates and the intervention catalogue.

This is *prior knowledge about how an e-commerce operation works*, shared by the planner and by the
simulated enterprise systems. It contains no scenario ground truth.
"""
from __future__ import annotations

CAUSE_LABEL = {
    "logistics_partner_change": "Last-mile partner change",
    "traffic_congestion": "Traffic congestion",
    "warehouse_dispatch": "Warehouse dispatch delay",
    "release_regression": "Software release regression",
    "gateway_degradation": "Payment gateway degradation",
    "external_os_update": "External OS / platform update",
    "supplier_quality": "Supplier quality change",
    "demand_surge": "Demand surge / promotion",
    "refund_pipeline_backlog": "Refund pipeline backlog",
    "support_capacity": "Support capacity shortfall",
    "infra_latency": "Infrastructure latency",
    "weather": "Adverse weather",
    "config_change": "Configuration change",
}

# Hypothesis templates per issue aspect. `events`: event_types to match; `components`: release components;
# `metric`: continuous operational metric whose elevation would corroborate; `keywords`: customer-voice mechanism terms.
ASPECT_CAUSES: dict[str, list[dict]] = {
    "delivery": [
        {"cause_type": "logistics_partner_change", "events": ["partner_change"], "keywords": ["courier", "partner", "rider", "executive", "handled", "hub"],
         "prior": 0.5, "entity_dim": "delivery_partner", "data_needed": ["Per-partner SLA and handover logs", "Partner onboarding checklist and routing coverage"]},
        {"cause_type": "traffic_congestion", "events": ["traffic_alert"], "metric": "traffic_congestion_index", "metric_dim": "city",
         "keywords": ["traffic", "jam", "road", "congestion", "blocked", "closures"], "prior": 0.4, "gap_ok": True,
         "data_needed": ["City traffic congestion feed for every operating city", "Route-level transit times"]},
        {"cause_type": "warehouse_dispatch", "events": [], "metric": "warehouse_dispatch_hours", "metric_dim": "warehouse",
         "keywords": ["dispatch", "warehouse", "packed", "not shipped"], "prior": 0.35, "gap_ok": True,
         "data_needed": ["Warehouse dispatch timestamps per fulfilment centre", "Pick-pack-ship cycle times"]},
        {"cause_type": "release_regression", "components": ["logistics-routing"], "keywords": ["tracking", "assigned", "wrong"], "prior": 0.3,
         "data_needed": ["Routing service assignment logs before and after release"]},
        {"cause_type": "weather", "events": ["weather"], "keywords": ["rain", "flood", "storm"], "prior": 0.2,
         "data_needed": ["Hourly weather observations per city"]},
    ],
    "payment": [
        {"cause_type": "gateway_degradation", "events": ["incident"], "metric": "gateway_availability", "metric_dim": "gateway", "low_is_bad": True,
         "keywords": ["timeout", "timed out", "otp", "3d", "gateway", "debited", "deducted"], "prior": 0.5,
         "data_needed": ["Gateway-level authorisation response codes", "Vendor incident post-mortem"]},
        {"cause_type": "release_regression", "components": ["checkout-service", "payments-sdk"], "keywords": ["update", "checkout", "app"], "prior": 0.3,
         "data_needed": ["Checkout error logs split by service version"]},
        {"cause_type": "config_change", "events": ["config_change"], "keywords": ["retry", "checkout"], "prior": 0.2,
         "data_needed": ["Configuration change diff and rollback plan"]},
        {"cause_type": "demand_surge", "events": ["promotion"], "keywords": ["sale", "offer"], "prior": 0.15,
         "data_needed": ["Peak traffic and concurrency metrics"]},
    ],
    "app": [
        {"cause_type": "release_regression", "components": ["mobile-app", "ios-app"], "keywords": ["update", "version", "latest", "7.8", "crash"], "prior": 0.5,
         "data_needed": ["Crash stack traces grouped by app build", "Feature-flag rollout state"]},
        {"cause_type": "external_os_update", "events": ["external"], "keywords": ["android", "os update", "patch"], "prior": 0.3,
         "data_needed": ["Crash rate by OS patch level"]},
        {"cause_type": "infra_latency", "events": [], "metric": "api_p95_latency_ms", "metric_dim": "entity", "keywords": ["slow", "loading", "hang"],
         "prior": 0.2, "gap_ok": False, "data_needed": ["Backend API latency traces"]},
    ],
    "product_quality": [
        {"cause_type": "supplier_quality", "events": ["supplier_change"], "keywords": ["batch", "heating", "stopped", "burn", "died", "defective"], "prior": 0.5,
         "data_needed": ["Supplier QC inspection reports by batch", "Returned unit teardown analysis"]},
        {"cause_type": "demand_surge", "events": ["promotion"], "keywords": ["sale", "offer"], "prior": 0.2,
         "data_needed": ["Order volume by SKU during the promotion"]},
    ],
    "refund": [
        {"cause_type": "refund_pipeline_backlog", "events": ["migration", "incident"], "components": ["refund-service"], "metric": "refund_queue_depth",
         "metric_dim": "entity", "keywords": ["processing", "system", "initiated", "stuck", "credited"], "prior": 0.5,
         "data_needed": ["Refund job run logs and failure reasons", "Finance ledger reconciliation status"]},
        {"cause_type": "support_capacity", "events": ["staffing"], "metric": "support_backlog", "metric_dim": "entity",
         "keywords": ["support", "agent", "no reply", "response"], "prior": 0.25,
         "data_needed": ["Agent availability and ticket handling times"]},
        {"cause_type": "gateway_degradation", "events": [], "metric": "gateway_availability", "metric_dim": "gateway", "low_is_bad": True,
         "keywords": ["bank", "reversal"], "prior": 0.15, "data_needed": ["Bank refund-rail acknowledgements"]},
    ],
}

SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

# beta: churn uplift per affected customer for each issue aspect (assumption, see impact agent)
CHURN_BETA = {"delivery": 0.12, "payment": 0.15, "app": 0.10, "product_quality": 0.18, "refund": 0.20}
DEPARTMENT = {"delivery": "Logistics Operations", "payment": "Payments Engineering", "app": "Mobile Engineering",
              "product_quality": "Merchandising & Quality", "refund": "Finance Operations"}

# role: root_cause_fix | customer_mitigation | coordination
INTERVENTIONS: dict[str, dict] = {
    "reassign_delivery_partner": {
        "title": "Reassign affected zones to a proven delivery partner", "role": "root_cause_fix", "consequential": True,
        "addresses": {"logistics_partner_change": 0.85, "warehouse_dispatch": 0.05}, "cost_fixed": 75000, "cost_per_unit": 12, "hours": 24,
        "risk": 0.30, "feasibility": 0.75, "reversibility": 0.85, "department": "Logistics Operations", "change": "partner_reassignment",
        "tools": ["create_service_ticket", "assign_incident", "apply_operational_change"]},
    "dynamic_rerouting_surge_capacity": {
        "title": "Enable congestion-aware routing and add surge delivery capacity", "role": "root_cause_fix", "consequential": True,
        "addresses": {"traffic_congestion": 0.55, "logistics_partner_change": 0.25, "warehouse_dispatch": 0.10}, "cost_fixed": 90000,
        "cost_per_unit": 20, "hours": 36, "risk": 0.25, "feasibility": 0.70, "reversibility": 0.80, "department": "Logistics Operations",
        "change": "capacity_routing", "tools": ["create_service_ticket", "assign_incident", "apply_operational_change"]},
    "warehouse_dispatch_fix": {
        "title": "Add warehouse shifts and re-prioritise dispatch queue", "role": "root_cause_fix", "consequential": True,
        "addresses": {"warehouse_dispatch": 0.8}, "cost_fixed": 60000, "cost_per_unit": 5, "hours": 24, "risk": 0.2, "feasibility": 0.7,
        "reversibility": 0.9, "department": "Fulfilment Operations", "change": "warehouse_capacity",
        "tools": ["create_service_ticket", "assign_incident", "apply_operational_change"]},
    "temporary_release_rollback": {
        "title": "Temporarily roll back the suspect release", "role": "root_cause_fix", "consequential": True,
        "addresses": {"release_regression": 0.92, "config_change": 0.8}, "cost_fixed": 120000, "cost_per_unit": 0, "hours": 6, "risk": 0.30,
        "feasibility": 0.85, "reversibility": 0.90, "department": "Platform Engineering", "change": "release_rollback",
        "tools": ["create_service_ticket", "assign_incident", "apply_operational_change"]},
    "hotfix_release": {
        "title": "Ship a targeted hotfix for the regression", "role": "root_cause_fix", "consequential": True,
        "addresses": {"release_regression": 0.80}, "cost_fixed": 160000, "cost_per_unit": 0, "hours": 48, "risk": 0.35, "feasibility": 0.55,
        "reversibility": 0.70, "department": "Platform Engineering", "change": "hotfix",
        "tools": ["create_service_ticket", "assign_incident", "apply_operational_change"]},
    "payment_gateway_failover": {
        "title": "Fail over card traffic to the backup payment gateway", "role": "root_cause_fix", "consequential": True,
        "addresses": {"gateway_degradation": 0.88}, "cost_fixed": 80000, "cost_per_unit": 3, "hours": 4, "risk": 0.30, "feasibility": 0.80,
        "reversibility": 0.95, "department": "Payments Engineering", "change": "gateway_failover",
        "tools": ["create_service_ticket", "assign_incident", "apply_operational_change"]},
    "supplier_batch_hold_recall": {
        "title": "Hold the suspect supplier batch and start a recall", "role": "root_cause_fix", "consequential": True,
        "addresses": {"supplier_quality": 0.90}, "cost_fixed": 150000, "cost_per_unit": 80, "hours": 24, "risk": 0.35, "feasibility": 0.70,
        "reversibility": 0.60, "department": "Merchandising & Quality", "change": "supplier_hold",
        "tools": ["create_service_ticket", "assign_incident", "apply_operational_change"]},
    "refund_backlog_clearance": {
        "title": "Clear the refund backlog manually and fix the batch pipeline", "role": "root_cause_fix", "consequential": True,
        "addresses": {"refund_pipeline_backlog": 0.85, "support_capacity": 0.2}, "cost_fixed": 70000, "cost_per_unit": 10, "hours": 24,
        "risk": 0.25, "feasibility": 0.75, "reversibility": 0.85, "department": "Finance Operations", "change": "refund_pipeline_fix",
        "tools": ["create_service_ticket", "assign_incident", "apply_operational_change"]},
    "add_support_capacity": {
        "title": "Add temporary support agents and extend hours", "role": "root_cause_fix", "consequential": True,
        "addresses": {"support_capacity": 0.65}, "cost_fixed": 55000, "cost_per_unit": 4, "hours": 48, "risk": 0.15, "feasibility": 0.8,
        "reversibility": 0.95, "department": "Customer Support", "change": "support_capacity",
        "tools": ["create_service_ticket", "assign_incident", "apply_operational_change"]},
    "proactive_customer_notification": {
        "title": "Send proactive status notifications to affected customers", "role": "customer_mitigation", "consequential": True,
        "addresses": {}, "cost_fixed": 3000, "cost_per_unit": 2, "hours": 2, "risk": 0.05, "feasibility": 0.95, "reversibility": 0.5,
        "department": "Customer Communications", "change": None, "complaint_mult": 0.80, "tools": ["send_customer_notification"]},
    "compensation_voucher": {
        "title": "Issue goodwill vouchers to severely affected customers", "role": "customer_mitigation", "consequential": True,
        "addresses": {}, "cost_fixed": 5000, "cost_per_unit": 150, "hours": 12, "risk": 0.20, "feasibility": 0.85, "reversibility": 0.30,
        "department": "Customer Experience", "change": None, "complaint_mult": 0.70,
        "tools": ["create_refund_approval_request", "send_customer_notification"]},
    "prioritise_support_queue": {
        "title": "Prioritise affected customers in the support queue", "role": "customer_mitigation", "consequential": False,
        "addresses": {}, "cost_fixed": 4000, "cost_per_unit": 1, "hours": 4, "risk": 0.05, "feasibility": 0.9, "reversibility": 0.95,
        "department": "Customer Support", "change": None, "complaint_mult": 0.90, "tools": ["create_service_ticket", "assign_incident"]},
    "create_technical_incident": {
        "title": "Open a technical incident and assign an owner", "role": "coordination", "consequential": False,
        "addresses": {}, "cost_fixed": 2000, "cost_per_unit": 0, "hours": 1, "risk": 0.02, "feasibility": 0.98, "reversibility": 1.0,
        "department": "Incident Management", "change": None, "tools": ["create_service_ticket", "assign_incident"]},
    "escalate_to_owner_department": {
        "title": "Escalate to the responsible department head", "role": "coordination", "consequential": False,
        "addresses": {}, "cost_fixed": 1000, "cost_per_unit": 0, "hours": 1, "risk": 0.02, "feasibility": 0.98, "reversibility": 1.0,
        "department": "Executive Operations", "change": None, "tools": ["create_escalation_request"]},
}

BEST_FOR_CAUSE = {  # used by the benchmark only
    "logistics_partner_change": ["reassign_delivery_partner", "dynamic_rerouting_surge_capacity"],
    "traffic_congestion": ["dynamic_rerouting_surge_capacity"],
    "release_regression": ["temporary_release_rollback", "hotfix_release"],
    "gateway_degradation": ["payment_gateway_failover"],
    "supplier_quality": ["supplier_batch_hold_recall"],
    "refund_pipeline_backlog": ["refund_backlog_clearance"],
    "warehouse_dispatch": ["warehouse_dispatch_fix"],
    "support_capacity": ["add_support_capacity"],
}
