import uuid
from collections.abc import Iterator
from decimal import Decimal

import pytest
from dashboard.api import create_app
from db.models import Action, AuditLog, Base, Finding, Incident
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _register_gen_random_uuid(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
        dbapi_connection.create_function("gen_random_uuid", 0, lambda: uuid.uuid4().hex)

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    # Used only to seed fixtures and to make assertions from outside the
    # app's own request-scoped sessions. StaticPool keeps the same
    # in-memory SQLite database alive across every separate Session(engine)
    # instantiation, including the ones create_app's session_factory makes
    # per-request, so commits made by the app are visible here.
    with Session(engine) as session:
        yield session


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
    session.commit()
    return action


def _client_with_role(engine: Engine, has_role: bool) -> TestClient:
    app = create_app(
        session_factory=lambda: Session(engine),
        role_checker=lambda discord_user_id: has_role,
        current_user_id=lambda request: "dev-user",
    )
    return TestClient(app)


def test_list_incidents_returns_seeded_incident(session: Session, engine: Engine) -> None:
    _seed_pending_action(session)
    client = _client_with_role(engine, has_role=True)

    response = client.get("/incidents")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert "created_at" in body[0]


def test_get_incident_includes_finding_confidence(session: Session, engine: Engine) -> None:
    _seed_pending_action(session)
    client = _client_with_role(engine, has_role=True)

    incident = session.query(Incident).one()
    response = client.get(f"/incidents/{incident.id}")

    assert response.status_code == 200
    findings = response.json()["findings"]
    assert len(findings) == 1
    assert findings[0]["confidence"] == "high"


def test_approve_without_role_is_forbidden(session: Session, engine: Engine) -> None:
    action = _seed_pending_action(session)
    client = _client_with_role(engine, has_role=False)

    response = client.post(f"/actions/{action.id}/approve")

    assert response.status_code == 403
    # Re-query via a brand new session to prove nothing was committed by
    # the (rejected) request, not just that the seeding session's own
    # in-memory object still looks unpersisted.
    with Session(engine) as verify_session:
        refetched = verify_session.get(Action, action.id)
        assert refetched is not None
        assert refetched.status == "pending"


def test_approve_with_role_succeeds(session: Session, engine: Engine) -> None:
    action = _seed_pending_action(session)
    client = _client_with_role(engine, has_role=True)

    response = client.post(f"/actions/{action.id}/approve")

    assert response.status_code == 200
    # This is the crux of Finding 1's fix: the app used an entirely
    # separate Session(engine) instance to handle the request. Reading
    # the row back through a THIRD, fresh session (not the request's
    # session, not the seeding session) proves the write was actually
    # committed to the database rather than left dangling in some
    # request-scoped session's uncommitted transaction.
    with Session(engine) as verify_session:
        refetched = verify_session.get(Action, action.id)
        assert refetched is not None
        assert refetched.status == "approved"
        assert refetched.approved_by == "dev-user"

        audit_rows = verify_session.query(AuditLog).filter_by(incident_id=action.incident_id).all()
        assert len(audit_rows) == 1
        assert audit_rows[0].event_type == "approval"
        assert audit_rows[0].actor.startswith("dashboard:")


def test_approve_rejected_after_role_revoked_mid_session(session: Session, engine: Engine) -> None:
    action = _seed_pending_action(session)
    role_state = {"has_role": True}
    app = create_app(
        session_factory=lambda: Session(engine),
        role_checker=lambda discord_user_id: role_state["has_role"],
    )
    client = TestClient(app)

    role_state["has_role"] = False
    response = client.post(f"/actions/{action.id}/approve")

    assert response.status_code == 403
    with Session(engine) as verify_session:
        refetched = verify_session.get(Action, action.id)
        assert refetched is not None
        assert refetched.status == "pending"


def test_reject_requires_reason_body(session: Session, engine: Engine) -> None:
    action = _seed_pending_action(session)
    client = _client_with_role(engine, has_role=True)

    response = client.post(f"/actions/{action.id}/reject", json={"reason": "too risky"})

    assert response.status_code == 200
    with Session(engine) as verify_session:
        refetched = verify_session.get(Action, action.id)
        assert refetched is not None
        assert refetched.status == "rejected"
        assert refetched.rejection_reason == "too risky"

        audit_rows = verify_session.query(AuditLog).filter_by(incident_id=action.incident_id).all()
        assert len(audit_rows) == 1
        assert audit_rows[0].event_type == "rejection"
        assert audit_rows[0].actor.startswith("dashboard:")
