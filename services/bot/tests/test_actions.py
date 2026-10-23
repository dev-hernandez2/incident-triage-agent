import uuid

import pytest
from bot.actions import approve_action, reject_action
from db.models import Action, AuditLog, Base
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _register_gen_random_uuid(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
        dbapi_connection.create_function("gen_random_uuid", 0, lambda: uuid.uuid4().hex)

    Base.metadata.create_all(engine)
    return Session(engine)


def _make_pending_action(session: Session) -> Action:
    action = Action(
        incident_id=uuid.uuid4(),
        finding_id=uuid.uuid4(),
        type="rollback",
        deployment="cartservice",
        replicas=None,
        reason="bad deploy",
        status="pending",
    )
    session.add(action)
    session.flush()
    return action


def test_approve_action_without_role_is_forbidden_and_does_not_change_state(
    session: Session,
) -> None:
    action = _make_pending_action(session)

    result = approve_action(session, action, approver_id="user-1", has_role=False)

    assert result == "forbidden"
    assert action.status == "pending"
    assert action.approved_by is None
    assert session.query(AuditLog).count() == 0


def test_approve_action_with_role_transitions_to_approved_and_writes_audit_log(
    session: Session,
) -> None:
    action = _make_pending_action(session)

    result = approve_action(session, action, approver_id="user-1", has_role=True)

    assert result == "approved"
    assert action.status == "approved"
    assert action.approved_by == "user-1"
    assert action.approved_at is not None

    logs = session.query(AuditLog).all()
    assert len(logs) == 1
    assert logs[0].event_type == "approval"
    assert logs[0].actor == "bot:user-1"
    assert logs[0].incident_id == action.incident_id


def test_approve_action_already_decided_is_a_no_op(session: Session) -> None:
    action = _make_pending_action(session)
    action.status = "rejected"
    session.flush()

    result = approve_action(session, action, approver_id="user-1", has_role=True)

    assert result == "already_decided"
    assert action.status == "rejected"
    assert session.query(AuditLog).count() == 0


def test_reject_action_without_role_is_forbidden(session: Session) -> None:
    action = _make_pending_action(session)

    result = reject_action(
        session, action, rejecter_id="user-1", reason="too risky", has_role=False
    )

    assert result == "forbidden"
    assert action.status == "pending"


def test_reject_action_with_role_transitions_to_rejected_with_reason(session: Session) -> None:
    action = _make_pending_action(session)

    result = reject_action(
        session, action, rejecter_id="user-2", reason="too risky", has_role=True
    )

    assert result == "rejected"
    assert action.status == "rejected"
    assert action.rejection_reason == "too risky"

    logs = session.query(AuditLog).all()
    assert len(logs) == 1
    assert logs[0].event_type == "rejection"
    assert logs[0].detail["reason"] == "too risky"


def test_approve_action_with_dashboard_actor_prefix_is_labeled_accordingly(
    session: Session,
) -> None:
    action = _make_pending_action(session)

    result = approve_action(
        session, action, approver_id="user-1", has_role=True, actor_prefix="dashboard"
    )

    assert result == "approved"
    logs = session.query(AuditLog).all()
    assert len(logs) == 1
    assert logs[0].actor == "dashboard:user-1"


def test_reject_action_with_dashboard_actor_prefix_is_labeled_accordingly(
    session: Session,
) -> None:
    action = _make_pending_action(session)

    result = reject_action(
        session,
        action,
        rejecter_id="user-2",
        reason="too risky",
        has_role=True,
        actor_prefix="dashboard",
    )

    assert result == "rejected"
    logs = session.query(AuditLog).all()
    assert len(logs) == 1
    assert logs[0].actor == "dashboard:user-2"
