"""Execution agent: retries, idempotency, failure handling and rollback (independent of the main workflow DB)."""
import importlib
import os
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from app.core.config import get_settings


@pytest.fixture()
def db():
    from app.db import Base, SessionLocal, init_engine

    eng = init_engine(f"sqlite:///{(Path(tempfile.mkdtemp()) / 'exec.db').as_posix()}")
    import app.models  # noqa: F401

    Base.metadata.create_all(eng)
    s = SessionLocal()
    yield s
    s.close()
    # restore the shared engine used by the API tests
    init_engine(os.environ["DATABASE_URL"])


def _intervention(db, status="approved", itype="reassign_delivery_partner"):
    from app.models import DetectedIssue, Intervention
    from app.services.system import set_sim_now

    set_sim_now(db, datetime(2026, 10, 31))
    issue = DetectedIssue(code="ISS-9999", title="t", category="Delivery Delays", aspect="delivery", status="open", severity="high")
    db.add(issue)
    db.flush()
    iv = Intervention(code="INT-9999", issue_id=issue.id, intervention_type=itype, title="Reassign", role="root_cause_fix", status=status, params={"department": "Logistics", "units": 10, "change": "partner_reassignment", "aspect": "delivery"})
    db.add(iv)
    db.commit()
    return iv


def test_only_approved_interventions_can_execute(db):
    from app.agents import execution_agent
    from app.agents.context import Ctx

    iv = _intervention(db, status="pending_approval")
    with pytest.raises(PermissionError):
        execution_agent.execute(Ctx(db, "t"), iv.id)


def test_transient_failures_are_retried_and_idempotent(db, monkeypatch):
    from app.agents import execution_agent
    from app.agents.context import Ctx
    from app.models import ExecutionLog

    monkeypatch.setattr(get_settings(), "tool_failure_rate", 0.99)  # first attempt of ~every tool fails
    iv = _intervention(db)
    res = execution_agent.execute(Ctx(db, "t"), iv.id)
    assert res.status == "succeeded" and iv.status == "executed"
    logs = db.query(ExecutionLog).filter_by(intervention_id=iv.id).all()
    assert any(l.status == "retrying" for l in logs) and sum(1 for l in logs if l.status == "success") == 3
    # replaying the same execution must not create new side-effects
    iv.status = "failed"
    db.commit()
    n_success = sum(1 for l in db.query(ExecutionLog).filter_by(intervention_id=iv.id, status="success"))
    execution_agent.execute(Ctx(db, "t2"), iv.id)
    assert sum(1 for l in db.query(ExecutionLog).filter_by(intervention_id=iv.id, status="success")) == n_success
    assert db.query(ExecutionLog).filter_by(intervention_id=iv.id, status="skipped").count() == 3


def test_permanent_failure_marks_failed_and_compensates(db, monkeypatch):
    from app.agents import execution_agent
    from app.agents.context import Ctx
    from app.models import ExecutionLog, ServiceTicket
    from app.tools import enterprise

    def boom(db, iv, args):
        raise enterprise.PermanentToolError("403 forbidden by simulated change-management policy")

    monkeypatch.setattr(get_settings(), "tool_failure_rate", 0.0)
    monkeypatch.setitem(enterprise.TOOLS, "apply_operational_change", (boom, enterprise.TOOLS["apply_operational_change"][1], "Operations Control Plane"))
    iv = _intervention(db)
    res = execution_agent.execute(Ctx(db, "t"), iv.id)
    assert res.status == "failed" and iv.status == "failed"
    assert res.output["compensated"] == ["assign_incident", "create_service_ticket"]
    assert db.query(ExecutionLog).filter_by(intervention_id=iv.id, status="rolled_back").count() == 2
    assert all(t.status == "cancelled" for t in db.query(ServiceTicket).filter_by(intervention_id=iv.id))


def test_manual_rollback_of_executed_intervention(db, monkeypatch):
    from app.agents import execution_agent
    from app.agents.context import Ctx

    monkeypatch.setattr(get_settings(), "tool_failure_rate", 0.0)
    iv = _intervention(db)
    execution_agent.execute(Ctx(db, "t"), iv.id)
    res = execution_agent.rollback(Ctx(db, "t"), iv.id)
    assert iv.status == "rolled_back" and res.output["status"] == "rolled_back"
    with pytest.raises(PermissionError):
        execution_agent.rollback(Ctx(db, "t"), iv.id)


def test_alembic_migration_builds_the_full_schema(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    from app.core.config import SERVER_DIR
    from app.db import Base, init_engine

    eng = init_engine(f"sqlite:///{(tmp_path / 'mig.db').as_posix()}")
    cfg = Config(str(SERVER_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVER_DIR / "alembic"))
    command.upgrade(cfg, "head")
    tables = set(inspect(eng).get_table_names())
    expected = {t for t in Base.metadata.tables}
    assert expected <= tables
    for required in ("users", "roles", "customers", "customer_segments", "data_sources", "customer_signals", "operational_events", "product_releases", "detected_issues",
                     "issue_clusters", "issue_evidence", "root_cause_hypotheses", "hypothesis_evidence", "business_impact_estimates", "interventions", "intervention_comparisons",
                     "approval_requests", "execution_logs", "recovery_kpis", "recovery_measurements", "agent_execution_history", "dynamic_scenarios", "audit_logs"):
        assert required in tables, required
    init_engine(os.environ["DATABASE_URL"])
    _ = importlib
