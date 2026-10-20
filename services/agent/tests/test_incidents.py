"""Tests for idempotent incident upsert logic."""

import uuid

from agent.incidents import upsert_incident
from agent.messages import AlertMessage
from db.models import Base, Incident
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

FIRING = AlertMessage(
    fingerprint="abc123",
    status="firing",
    alertname="BoutiquePodCrashLooping",
    labels={"pod": "cartservice-abc"},
    annotations={},
    starts_at="2026-10-16T10:00:00Z",
    ends_at=None,
)

RESOLVED = AlertMessage(
    fingerprint="abc123",
    status="resolved",
    alertname="BoutiquePodCrashLooping",
    labels={"pod": "cartservice-abc"},
    annotations={},
    starts_at="2026-10-16T10:00:00Z",
    ends_at="2026-10-16T10:05:00Z",
)


def make_session() -> Session:
    # SQLite has no built-in gen_random_uuid(), but the Incident model's
    # id column uses server_default=text("gen_random_uuid()") for Postgres.
    # Register a Python stand-in so the same server_default works here too,
    # without touching the model (Postgres keeps using its own builtin).
    #
    # The stand-in must return a dashless 32-char hex string, not
    # str(uuid.uuid4()) (which is dashed). Incident.id uses
    # postgresql.UUID(as_uuid=True), whose bind_processor on the SQLite
    # dialect strips dashes when binding a uuid.UUID value as a query
    # parameter, but a server-side default (like this function) bypasses
    # that bind_processor entirely — SQLite stores whatever string the
    # function literally returns. If that string is dashed, it won't match
    # the dashless parameter SQLAlchemy binds when re-SELECTing the row
    # after session.commit() expires the instance, causing a spurious
    # ObjectDeletedError on the next attribute access. Returning
    # uuid.uuid4().hex (dashless) keeps the stored and bound
    # representations consistent.
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _register_gen_random_uuid(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
        dbapi_connection.create_function("gen_random_uuid", 0, lambda: uuid.uuid4().hex)

    Base.metadata.create_all(engine)
    return Session(engine)


def test_firing_message_creates_incident() -> None:
    session = make_session()
    incident = upsert_incident(session, FIRING)
    session.commit()
    assert incident is not None
    assert incident.fingerprint == "abc123"
    assert incident.status == "received"


def test_firing_message_stores_annotations() -> None:
    message = AlertMessage(
        fingerprint="abc456",
        status="firing",
        alertname="BoutiquePodCrashLooping",
        labels={"pod": "cartservice-abc"},
        annotations={"summary": "cartservice is restarting repeatedly"},
        starts_at="2026-10-16T10:00:00Z",
        ends_at=None,
    )
    session = make_session()
    incident = upsert_incident(session, message)
    session.commit()
    assert incident is not None
    assert incident.annotations == {"summary": "cartservice is restarting repeatedly"}


def test_duplicate_firing_message_is_noop() -> None:
    session = make_session()
    first = upsert_incident(session, FIRING)
    session.commit()
    assert first is not None

    second = upsert_incident(session, FIRING)
    session.commit()
    assert second is None

    rows = session.query(Incident).filter_by(fingerprint="abc123").all()
    assert len(rows) == 1


def test_resolved_message_updates_matching_received_row() -> None:
    session = make_session()
    upsert_incident(session, FIRING)
    session.commit()

    resolved = upsert_incident(session, RESOLVED)
    session.commit()
    assert resolved is not None
    assert resolved.status == "resolved"


def test_resolved_message_with_no_matching_row_is_noop() -> None:
    session = make_session()
    result = upsert_incident(session, RESOLVED)
    session.commit()
    assert result is None
    assert session.query(Incident).count() == 0
