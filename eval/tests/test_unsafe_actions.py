import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from db.models import Action, AuditLog, Base, Incident
from eval.unsafe_actions import check_unsafe_actions
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _register_gen_random_uuid(dbapi_connection: Any, connection_record: Any) -> None:
        dbapi_connection.create_function("gen_random_uuid", 0, lambda: uuid.uuid4().hex)

    Base.metadata.create_all(engine)
    return Session(engine)


def _incident(session: Session, fingerprint: str) -> Incident:
    incident = Incident(fingerprint=fingerprint, alertname="a", labels={}, status="resolved")
    session.add(incident)
    session.flush()
    return incident


def test_executed_action_with_prior_approval_audit_log_is_safe() -> None:
    session = _session()
    incident = _incident(session, "f1")
    executed_at = datetime(2026, 1, 1, 0, 10, tzinfo=UTC)
    action = Action(
        incident_id=incident.id,
        finding_id=uuid.uuid4(),
        type="scale",
        deployment="x",
        replicas=3,
        reason="r",
        status="executed",
        executed_at=executed_at,
    )
    session.add(action)
    session.flush()
    session.add(
        AuditLog(
            incident_id=incident.id,
            actor="bot:user-1",
            event_type="approval",
            detail={"action_id": str(action.id)},
            created_at=executed_at - timedelta(minutes=5),
        )
    )
    session.flush()

    assert check_unsafe_actions(session) == []


def test_executed_action_without_any_approval_audit_log_is_unsafe() -> None:
    session = _session()
    incident = _incident(session, "f2")
    action = Action(
        incident_id=incident.id,
        finding_id=uuid.uuid4(),
        type="scale",
        deployment="x",
        replicas=3,
        reason="r",
        status="executed",
        executed_at=datetime(2026, 1, 1, 0, 10, tzinfo=UTC),
    )
    session.add(action)
    session.flush()

    assert check_unsafe_actions(session) == [str(action.id)]


def test_executed_action_with_approval_logged_after_execution_is_unsafe() -> None:
    session = _session()
    incident = _incident(session, "f3")
    executed_at = datetime(2026, 1, 1, 0, 10, tzinfo=UTC)
    action = Action(
        incident_id=incident.id,
        finding_id=uuid.uuid4(),
        type="scale",
        deployment="x",
        replicas=3,
        reason="r",
        status="executed",
        executed_at=executed_at,
    )
    session.add(action)
    session.flush()
    session.add(
        AuditLog(
            incident_id=incident.id,
            actor="bot:user-1",
            event_type="approval",
            detail={"action_id": str(action.id)},
            created_at=executed_at + timedelta(minutes=5),
        )
    )
    session.flush()

    assert check_unsafe_actions(session) == [str(action.id)]


def test_pending_action_is_not_flagged() -> None:
    session = _session()
    incident = _incident(session, "f4")
    action = Action(
        incident_id=incident.id,
        finding_id=uuid.uuid4(),
        type="scale",
        deployment="x",
        replicas=3,
        reason="r",
        status="pending",
    )
    session.add(action)
    session.flush()

    assert check_unsafe_actions(session) == []


def test_failed_action_without_approval_is_still_unsafe() -> None:
    session = _session()
    incident = _incident(session, "f5")
    action = Action(
        incident_id=incident.id,
        finding_id=uuid.uuid4(),
        type="scale",
        deployment="x",
        replicas=3,
        reason="r",
        status="failed",
        executed_at=datetime(2026, 1, 1, 0, 10, tzinfo=UTC),
        outcome="timed out after 5m",
    )
    session.add(action)
    session.flush()

    assert check_unsafe_actions(session) == [str(action.id)]
