"""Relational schema for CX Sentinel AI (MySQL primary, SQLite fallback).

All datetimes are naive UTC. Domain timestamps (signals, events, KPIs) follow the simulated clock
stored in ``system_settings['sim_now']``; ``created_at`` style columns are wall-clock UTC.
"""
from sqlalchemy import (
    JSON, Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.mysql import DATETIME as MYSQL_DATETIME

from app.db import Base, utcnow

# MySQL DATETIME drops microseconds by default; the point-in-time replay of evidence needs them
DT = DateTime().with_variant(MYSQL_DATETIME(fsp=6), "mysql")


class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True)
    name = Column(String(32), unique=True, nullable=False)
    description = Column(String(255))


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(190), unique=True, nullable=False)
    full_name = Column(String(120), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DT, default=utcnow, nullable=False)
    last_login_at = Column(DT)
    role = relationship("Role", lazy="joined")


class CustomerSegment(Base):
    __tablename__ = "customer_segments"
    id = Column(Integer, primary_key=True)
    code = Column(String(40), unique=True, nullable=False)
    name = Column(String(120), nullable=False)
    description = Column(String(500))
    rule = Column(String(500))


class Customer(Base):
    """Pseudonymous customer profile. No names, emails or phone numbers are stored."""
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True)
    customer_ref = Column(String(40), unique=True, nullable=False)
    segment_id = Column(Integer, ForeignKey("customer_segments.id"), index=True)
    city = Column(String(60), index=True)
    region = Column(String(40))
    plan = Column(String(20), index=True)
    tenure_days = Column(Integer, default=0)
    lifetime_value = Column(Float, default=0.0)
    orders_90d = Column(Integer, default=0)
    complaints_90d = Column(Integer, default=0)
    platform = Column(String(20))
    os_version = Column(String(30))
    created_at = Column(DT, default=utcnow)
    segment = relationship("CustomerSegment", lazy="joined")


class DataSource(Base):
    __tablename__ = "data_sources"
    id = Column(Integer, primary_key=True)
    name = Column(String(160), nullable=False)
    source_type = Column(String(40), nullable=False, index=True)
    reliability = Column(Float, default=0.8, nullable=False)
    description = Column(String(500))
    is_simulated = Column(Boolean, default=False, nullable=False)
    file_name = Column(String(255))
    record_count = Column(Integer, default=0)
    rejected_count = Column(Integer, default=0)
    status = Column(String(30), default="active")
    uploaded_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DT, default=utcnow)
    last_ingested_at = Column(DT)


class Scenario(Base):
    """Dynamic jury scenario (injection + re-investigation)."""
    __tablename__ = "dynamic_scenarios"
    id = Column(Integer, primary_key=True)
    issue_id = Column(Integer, ForeignKey("detected_issues.id"), index=True)
    name = Column(String(160), nullable=False)
    scenario_type = Column(String(60), nullable=False)
    params = Column(JSON)
    injected_summary = Column(JSON)
    before_snapshot = Column(JSON)
    after_snapshot = Column(JSON)
    diff = Column(JSON)
    status = Column(String(30), default="created")
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DT, default=utcnow)


class CustomerSignal(Base):
    """Normalised evidence record (review, ticket, social, survey, transaction, telemetry, metric)."""
    __tablename__ = "customer_signals"
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("data_sources.id"), nullable=False, index=True)
    external_id = Column(String(120), nullable=False)
    revision = Column(Integer, default=1, nullable=False)
    is_current = Column(Boolean, default=True, nullable=False)
    source_type = Column(String(30), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), index=True)
    occurred_at = Column(DT, nullable=False)
    text = Column(Text)
    numeric_value = Column(Float)
    metric_name = Column(String(80))
    product = Column(String(160))
    segment = Column(String(40))
    region = Column(String(60))
    reliability = Column(Float, default=0.8, nullable=False)
    sentiment = Column(Float)
    primary_aspect = Column(String(30))
    aspects = Column(JSON)
    attributes = Column(JSON)
    content_hash = Column(String(40))
    is_flagged = Column(Boolean, default=False, nullable=False)
    flag_reason = Column(String(255))
    is_injected = Column(Boolean, default=False, nullable=False)
    scenario_id = Column(Integer, ForeignKey("dynamic_scenarios.id"))
    ingested_at = Column(DT, default=utcnow, nullable=False)
    __table_args__ = (
        Index("ix_signal_type_time", "source_type", "occurred_at"),
        Index("ix_signal_ext", "source_type", "external_id", "is_current"),
        Index("ix_signal_current_time", "is_current", "occurred_at"),
    )


class OperationalEvent(Base):
    __tablename__ = "operational_events"
    id = Column(Integer, primary_key=True)
    external_id = Column(String(120), unique=True, nullable=False)
    source_id = Column(Integer, ForeignKey("data_sources.id"))
    event_type = Column(String(40), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    entity = Column(String(120))
    city = Column(String(60))
    scope = Column(JSON)
    attributes = Column(JSON)
    severity = Column(String(20), default="info")
    start_at = Column(DT, nullable=False, index=True)
    end_at = Column(DT)
    reliability = Column(Float, default=0.85)
    is_injected = Column(Boolean, default=False, nullable=False)
    scenario_id = Column(Integer, ForeignKey("dynamic_scenarios.id"))
    created_at = Column(DT, default=utcnow)


class ProductRelease(Base):
    __tablename__ = "product_releases"
    id = Column(Integer, primary_key=True)
    external_id = Column(String(120), unique=True, nullable=False)
    source_id = Column(Integer, ForeignKey("data_sources.id"))
    component = Column(String(60), nullable=False, index=True)
    version = Column(String(40), nullable=False)
    title = Column(String(255))
    change_summary = Column(Text)
    deployed_at = Column(DT, nullable=False, index=True)
    scope = Column(JSON)
    rollback_available = Column(Boolean, default=True)
    risk_level = Column(String(20), default="medium")
    created_at = Column(DT, default=utcnow)


class DetectedIssue(Base):
    __tablename__ = "detected_issues"
    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True, nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    category = Column(String(60), nullable=False)
    aspect = Column(String(30), nullable=False, index=True)
    status = Column(String(30), default="open", nullable=False, index=True)
    severity = Column(String(20), default="medium", nullable=False)
    severity_score = Column(Float, default=0.0)
    severity_breakdown = Column(JSON)
    detection_confidence = Column(Float, default=0.0)
    support_count = Column(Integer, default=0)
    duplicate_count = Column(Integer, default=0)
    growth_rate = Column(Float, default=0.0)
    kpi_name = Column(String(60))
    baseline_rate = Column(Float)
    current_rate = Column(Float)
    first_detected_at = Column(DT)
    onset_at = Column(DT)
    stats = Column(JSON)
    iteration = Column(Integer, default=1, nullable=False)
    reopen_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DT, default=utcnow)
    updated_at = Column(DT, default=utcnow, onupdate=utcnow)


class IssueCluster(Base):
    __tablename__ = "issue_clusters"
    id = Column(Integer, primary_key=True)
    issue_id = Column(Integer, ForeignKey("detected_issues.id"), index=True)
    run_id = Column(String(40), index=True)
    cluster_label = Column(Integer)
    label = Column(String(255))
    top_terms = Column(JSON)
    aspect = Column(String(30))
    size = Column(Integer, default=0)
    daily_counts = Column(JSON)
    baseline_mean = Column(Float)
    recent_count = Column(Integer)
    expected_count = Column(Float)
    z_score = Column(Float)
    p_value = Column(Float)
    growth_rate = Column(Float)
    persistence_days = Column(Integer)
    is_new = Column(Boolean, default=False)
    is_anomalous = Column(Boolean, default=False)
    created_at = Column(DT, default=utcnow)


class IssueEvidence(Base):
    __tablename__ = "issue_evidence"
    id = Column(Integer, primary_key=True)
    issue_id = Column(Integer, ForeignKey("detected_issues.id"), nullable=False)
    signal_id = Column(Integer, ForeignKey("customer_signals.id"), nullable=False)
    cluster_id = Column(Integer, ForeignKey("issue_clusters.id"))
    relevance = Column(Float, default=1.0)
    is_duplicate = Column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("issue_id", "signal_id", name="uq_issue_signal"),)


class Investigation(Base):
    __tablename__ = "investigations"
    id = Column(Integer, primary_key=True)
    issue_id = Column(Integer, ForeignKey("detected_issues.id"), unique=True, nullable=False)
    status = Column(String(30), default="queued", nullable=False)
    stage = Column(String(40))
    iteration = Column(Integer, default=1)
    state = Column(JSON)
    created_at = Column(DT, default=utcnow)
    updated_at = Column(DT, default=utcnow, onupdate=utcnow)


class RootCauseHypothesis(Base):
    __tablename__ = "root_cause_hypotheses"
    id = Column(Integer, primary_key=True)
    issue_id = Column(Integer, ForeignKey("detected_issues.id"), nullable=False, index=True)
    iteration = Column(Integer, default=1, nullable=False)
    is_current = Column(Boolean, default=True, nullable=False)
    rank = Column(Integer)
    title = Column(String(255), nullable=False)
    cause_type = Column(String(50), nullable=False)
    statement = Column(Text)
    narrative = Column(Text)
    confidence = Column(Float, default=0.0, nullable=False)
    evidence_quality = Column(Float, default=0.0)
    quality_label = Column(String(20))
    status = Column(String(30), default="plausible")
    causal_claim = Column(String(255))
    alternatives = Column(JSON)
    additional_data_needed = Column(JSON)
    features = Column(JSON)
    scope = Column(JSON)
    created_at = Column(DT, default=utcnow)
    evidence = relationship("HypothesisEvidence", cascade="all, delete-orphan", lazy="selectin")


class HypothesisEvidence(Base):
    __tablename__ = "hypothesis_evidence"
    id = Column(Integer, primary_key=True)
    hypothesis_id = Column(Integer, ForeignKey("root_cause_hypotheses.id"), nullable=False, index=True)
    relation = Column(String(20), nullable=False)  # supports | contradicts | context
    kind = Column(String(30), nullable=False)  # statistic | event | release | metric | complaint_sample | conflict
    signal_id = Column(Integer, ForeignKey("customer_signals.id"))
    event_id = Column(Integer, ForeignKey("operational_events.id"))
    release_id = Column(Integer, ForeignKey("product_releases.id"))
    summary = Column(Text, nullable=False)
    weight = Column(Float, default=0.0)
    payload = Column(JSON)


class BusinessImpactEstimate(Base):
    __tablename__ = "business_impact_estimates"
    id = Column(Integer, primary_key=True)
    issue_id = Column(Integer, ForeignKey("detected_issues.id"), nullable=False, index=True)
    iteration = Column(Integer, default=1)
    is_current = Column(Boolean, default=True)
    metric = Column(String(60), nullable=False)
    label = Column(String(120))
    value = Column(Float)
    unit = Column(String(20))
    kind = Column(String(20), nullable=False)  # measured | estimated
    formula = Column(Text)
    inputs = Column(JSON)
    assumptions = Column(JSON)
    ci_low = Column(Float)
    ci_high = Column(Float)
    calculated_at = Column(DT, default=utcnow)


class Intervention(Base):
    __tablename__ = "interventions"
    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True, nullable=False)
    issue_id = Column(Integer, ForeignKey("detected_issues.id"), nullable=False, index=True)
    iteration = Column(Integer, default=1)
    intervention_type = Column(String(60), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    role = Column(String(30), default="root_cause_fix")
    params = Column(JSON)
    status = Column(String(30), default="proposed", nullable=False, index=True)
    verification_status = Column(String(30), default="not_started")
    requires_approval = Column(Boolean, default=True)
    is_consequential = Column(Boolean, default=True)
    expected_impact = Column(Float)
    cost_inr = Column(Float)
    execution_hours = Column(Float)
    customer_benefit = Column(Integer)
    business_risk = Column(Float)
    feasibility = Column(Float)
    confidence = Column(Float)
    reversibility = Column(Float)
    utility = Column(Float)
    rank = Column(Integer)
    is_recommended = Column(Boolean, default=False)
    rationale = Column(Text)
    target_hypothesis_id = Column(Integer, ForeignKey("root_cause_hypotheses.id"))
    created_at = Column(DT, default=utcnow)
    approved_at = Column(DT)
    executed_at = Column(DT)  # simulated clock
    verified_at = Column(DT)
    rolled_back_at = Column(DT)
    superseded = Column(Boolean, default=False)


class InterventionComparison(Base):
    __tablename__ = "intervention_comparisons"
    id = Column(Integer, primary_key=True)
    issue_id = Column(Integer, ForeignKey("detected_issues.id"), nullable=False, index=True)
    iteration = Column(Integer, default=1)
    intervention_id = Column(Integer, ForeignKey("interventions.id"), nullable=False)
    rank = Column(Integer)
    utility = Column(Float)
    criteria = Column(JSON)
    rationale = Column(Text)
    created_at = Column(DT, default=utcnow)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    id = Column(Integer, primary_key=True)
    intervention_id = Column(Integer, ForeignKey("interventions.id"), nullable=False, index=True)
    status = Column(String(20), default="pending", nullable=False, index=True)
    requested_at = Column(DT, default=utcnow)
    decided_by = Column(Integer, ForeignKey("users.id"))
    decided_at = Column(DT)
    comment = Column(Text)
    summary = Column(JSON)
    intervention = relationship("Intervention", lazy="joined")


class ExecutionLog(Base):
    __tablename__ = "execution_logs"
    id = Column(Integer, primary_key=True)
    intervention_id = Column(Integer, ForeignKey("interventions.id"), nullable=False, index=True)
    action = Column(String(60), nullable=False)
    simulated_system = Column(String(60))
    idempotency_key = Column(String(120), nullable=False)
    attempt = Column(Integer, default=1)
    status = Column(String(20), nullable=False)  # success | failed | retrying | skipped | rolled_back
    request = Column(JSON)
    response = Column(JSON)
    error = Column(Text)
    duration_ms = Column(Integer)
    created_at = Column(DT, default=utcnow)
    __table_args__ = (Index("ix_exec_idem", "idempotency_key"),)


class ServiceTicket(Base):
    """Simulated ITSM / ticketing system."""
    __tablename__ = "service_tickets"
    id = Column(Integer, primary_key=True)
    ticket_no = Column(String(30), unique=True, nullable=False)
    kind = Column(String(30), nullable=False)  # incident | escalation | refund_approval | support_priority
    department = Column(String(80))
    title = Column(String(255))
    body = Column(Text)
    priority = Column(String(20))
    status = Column(String(20), default="open")
    intervention_id = Column(Integer, ForeignKey("interventions.id"), index=True)
    created_at = Column(DT, default=utcnow)
    closed_at = Column(DT)


class CustomerNotification(Base):
    """Simulated notification gateway outbox."""
    __tablename__ = "customer_notifications"
    id = Column(Integer, primary_key=True)
    intervention_id = Column(Integer, ForeignKey("interventions.id"), index=True)
    channel = Column(String(20))
    audience = Column(JSON)
    recipients = Column(Integer, default=0)
    message = Column(Text)
    status = Column(String(20), default="queued")
    created_at = Column(DT, default=utcnow)


class RecoveryKpi(Base):
    __tablename__ = "recovery_kpis"
    id = Column(Integer, primary_key=True)
    code = Column(String(40), unique=True, nullable=False)
    name = Column(String(120), nullable=False)
    unit = Column(String(20))
    direction = Column(String(20), default="lower_better")
    target = Column(Float)
    description = Column(String(255))


class RecoveryMeasurement(Base):
    __tablename__ = "recovery_measurements"
    id = Column(Integer, primary_key=True)
    kpi_id = Column(Integer, ForeignKey("recovery_kpis.id"), nullable=False)
    issue_id = Column(Integer, ForeignKey("detected_issues.id"), index=True)
    intervention_id = Column(Integer, ForeignKey("interventions.id"), index=True)
    measured_on = Column(Date, nullable=False)
    value = Column(Float)
    numerator = Column(Float)
    denominator = Column(Float)
    phase = Column(String(20), default="history")  # history | pre | post
    is_simulated = Column(Boolean, default=True)
    __table_args__ = (Index("ix_meas_kpi_day", "kpi_id", "measured_on"),)


class AgentExecutionHistory(Base):
    __tablename__ = "agent_execution_history"
    id = Column(Integer, primary_key=True)
    run_id = Column(String(40), nullable=False, index=True)
    issue_id = Column(Integer, ForeignKey("detected_issues.id"), index=True)
    investigation_id = Column(Integer, ForeignKey("investigations.id"))
    agent = Column(String(60), nullable=False)
    task = Column(String(255))
    input_summary = Column(JSON)
    reasoning_summary = Column(Text)
    output_summary = Column(JSON)
    status = Column(String(20), nullable=False)
    attempt = Column(Integer, default=1)
    started_at = Column(DT, default=utcnow)
    finished_at = Column(DT)
    duration_ms = Column(Integer)
    llm_tokens_in = Column(Integer, default=0)
    llm_tokens_out = Column(Integer, default=0)
    llm_cost_usd = Column(Float, default=0.0)
    error = Column(Text)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    action = Column(String(80), nullable=False)
    entity_type = Column(String(60))
    entity_id = Column(String(60))
    detail = Column(JSON)
    ip_address = Column(String(64))
    created_at = Column(DT, default=utcnow, index=True)


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    level = Column(String(20), default="info")
    title = Column(String(200), nullable=False)
    body = Column(Text)
    link = Column(String(200))
    is_read = Column(Boolean, default=False)
    created_at = Column(DT, default=utcnow, index=True)


class SystemSetting(Base):
    __tablename__ = "system_settings"
    key = Column(String(80), primary_key=True)
    value = Column(JSON)
    updated_at = Column(DT, default=utcnow, onupdate=utcnow)

