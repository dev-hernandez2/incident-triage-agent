import uuid
from decimal import Decimal

import pytest
from dashboard.api import create_app
from db.models import Action, Base, Finding, Incident
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@pytest.fixture
def session() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _register_gen_random_uuid(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
        dbapi_connection.create_function("gen_random_uuid", 0, lambda: uuid.uuid4().hex)

    Base.metadata.create_all(engine)
    return Session(engine)


def _seed_pending_action(session: Session) -> Action:
    incident = Incident(fingerprint="f1", alertname="a", labels={}, status="received")
    session.add(incident)
    session.flush()
    finding = Finding(
        incident_id=incident.id,
        summary="s",
        root_cause="r",
        confidence="high",
        evidence=[],
        affected_services=[],
        suggested_fix={"type": "scale", "deployment": "x", "replicas": 3, "reason": "r"},
        ruled_out=[],
        status="complete",
        input_tokens=1,
        output_tokens=1,
        cost_usd=Decimal("0.01"),
    )
    session.add(finding)
    session.flush()
    action = Action(
        incident_id=incident.id,
        finding_id=finding.id,
        type="scale",
        deployment="x",
        replicas=3,
        reason="r",
        status="pending",
    )
    session.add(action)
    session.flush()
    return action


def _client_with_role(session: Session, has_role: bool) -> TestClient:
    app = create_app(
        session_factory=lambda: session,
        role_checker=lambda discord_user_id: has_role,
        current_user_id=lambda request: "dev-user",
    )
    return TestClient(app)


def test_list_incidents_returns_seeded_incident(session: Session) -> None:
    _seed_pending_action(session)
    client = _client_with_role(session, has_role=True)

    response = client.get("/incidents")

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_approve_without_role_is_forbidden(session: Session) -> None:
    action = _seed_pending_action(session)
    client = _client_with_role(session, has_role=False)

    response = client.post(f"/actions/{action.id}/approve")

    assert response.status_code == 403
    session.refresh(action)
    assert action.status == "pending"


def test_approve_with_role_succeeds(session: Session) -> None:
    action = _seed_pending_action(session)
    client = _client_with_role(session, has_role=True)

    response = client.post(f"/actions/{action.id}/approve")

    assert response.status_code == 200
    session.refresh(action)
    assert action.status == "approved"


def test_approve_rejected_after_role_revoked_mid_session(session: Session) -> None:
    action = _seed_pending_action(session)
    role_state = {"has_role": True}
    app = create_app(
        session_factory=lambda: session,
        role_checker=lambda discord_user_id: role_state["has_role"],
    )
    client = TestClient(app)

    role_state["has_role"] = False
    response = client.post(f"/actions/{action.id}/approve")

    assert response.status_code == 403
    session.refresh(action)
    assert action.status == "pending"


def test_reject_requires_reason_body(session: Session) -> None:
    action = _seed_pending_action(session)
    client = _client_with_role(session, has_role=True)

    response = client.post(f"/actions/{action.id}/reject", json={"reason": "too risky"})

    assert response.status_code == 200
    session.refresh(action)
    assert action.status == "rejected"
    assert action.rejection_reason == "too risky"
