import uuid
from datetime import UTC, datetime, timedelta

import pytest
from db.models import Action, AuditLog, Base, Incident
from executor.main import claim_approved_action, execute_action, poll_for_recovery
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session


class FakeK8sClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int | None]] = []

    def restart(self, deployment: str) -> None:
        self.calls.append(("restart", deployment, None))

    def scale(self, deployment: str, replicas: int) -> None:
        self.calls.append(("scale", deployment, replicas))

    def rollback(self, deployment: str) -> None:
        self.calls.append(("rollback", deployment, None))


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _register_gen_random_uuid(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
        dbapi_connection.create_function("gen_random_uuid", 0, lambda: uuid.uuid4().hex)

    Base.metadata.create_all(engine)
    return Session(engine)


def _approved_action(session: Session, incident_id: object, **overrides: object) -> Action:
    defaults: dict[str, object] = dict(
        incident_id=incident_id,
        finding_id=uuid.uuid4(),
        type="scale",
        deployment="checkoutservice",
        replicas=5,
        reason="under load",
        status="approved",
    )
    defaults.update(overrides)
    action = Action(**defaults)
    session.add(action)
    session.flush()
    return action


def test_claim_approved_action_moves_status_to_executing(session: Session) -> None:
    incident = Incident(fingerprint="f1", alertname="a", labels={}, status="received")
    session.add(incident)
    session.flush()
    action = _approved_action(session, incident.id)

    claimed = claim_approved_action(session)

    assert claimed is not None
    assert claimed.id == action.id
    assert claimed.status == "executing"


def test_claim_returns_none_when_no_approved_actions(session: Session) -> None:
    assert claim_approved_action(session) is None


def test_claim_is_atomic_under_concurrent_poll(session: Session) -> None:
    incident = Incident(fingerprint="f2", alertname="a", labels={}, status="received")
    session.add(incident)
    session.flush()
    _approved_action(session, incident.id)

    first = claim_approved_action(session)
    second = claim_approved_action(session)

    assert first is not None
    assert second is None


def test_execute_action_refuses_manual_type(session: Session) -> None:
    incident = Incident(fingerprint="f3", alertname="a", labels={}, status="received")
    session.add(incident)
    session.flush()
    action = _approved_action(
        session, incident.id, type="manual", deployment=None, replicas=None, status="executing"
    )
    fake_k8s = FakeK8sClient()

    execute_action(session, action, fake_k8s)

    assert fake_k8s.calls == []
    assert action.status == "failed"
    assert action.outcome == "refused: manual actions are never executed"


def test_execute_action_dispatches_scale(session: Session) -> None:
    incident = Incident(fingerprint="f4", alertname="a", labels={}, status="received")
    session.add(incident)
    session.flush()
    action = _approved_action(session, incident.id, status="executing")
    fake_k8s = FakeK8sClient()

    execute_action(session, action, fake_k8s)

    assert fake_k8s.calls == [("scale", "checkoutservice", 5)]
    assert action.executed_at is not None

    logs = session.query(AuditLog).filter_by(event_type="action_executed").all()
    assert len(logs) == 1


def test_poll_for_recovery_returns_true_when_incident_resolves(session: Session) -> None:
    incident = Incident(fingerprint="f5", alertname="a", labels={}, status="received")
    session.add(incident)
    session.flush()
    action = _approved_action(session, incident.id, status="executing")

    clock = {"now": datetime(2026, 1, 1, tzinfo=UTC)}
    calls = {"n": 0}

    def fake_sleep(seconds: float) -> None:
        calls["n"] += 1
        clock["now"] += timedelta(seconds=seconds)
        if calls["n"] == 2:
            incident.status = "resolved"
            session.flush()

    resolved = poll_for_recovery(
        session,
        action,
        timeout_seconds=300.0,
        poll_interval_seconds=10.0,
        sleep=fake_sleep,
        now=lambda: clock["now"],
    )

    assert resolved is True


def test_poll_for_recovery_times_out_after_5_minutes(session: Session) -> None:
    incident = Incident(fingerprint="f6", alertname="a", labels={}, status="received")
    session.add(incident)
    session.flush()
    action = _approved_action(session, incident.id, status="executing")

    clock = {"now": datetime(2026, 1, 1, tzinfo=UTC)}

    def fake_sleep(seconds: float) -> None:
        clock["now"] += timedelta(seconds=seconds)

    resolved = poll_for_recovery(
        session,
        action,
        timeout_seconds=300.0,
        poll_interval_seconds=10.0,
        sleep=fake_sleep,
        now=lambda: clock["now"],
    )

    assert resolved is False
