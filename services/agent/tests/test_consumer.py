"""Tests for the agent's message-processing logic (no live Kafka/Postgres)."""

import uuid
from decimal import Decimal

from agent.main import process_message
from db.models import Base, Incident
from llm.types import CompletionResult, ToolCallRequest, Usage
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

FIRING_RAW = (
    b'{"fingerprint": "abc123", "status": "firing", "alertname": "BoutiquePodCrashLooping", '
    b'"labels": {"pod": "cartservice-abc"}, "annotations": {}, '
    b'"starts_at": "2026-10-16T10:00:00Z", "ends_at": null}'
)

DUPLICATE_RAW = FIRING_RAW

MALFORMED_RAW = b"not json at all"


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


class _FakeLLMClient:
    def complete(
        self, messages: list[object], tools: list[dict[str, object]], system: str
    ) -> CompletionResult:
        good_args: dict[str, object] = {
            "summary": "stub",
            "root_cause": "stub",
            "confidence": "low",
            "evidence": [],
            "affected_services": [],
            "suggested_fix": "stub",
            "ruled_out": [],
        }
        return CompletionResult(
            text=None,
            tool_calls=[ToolCallRequest(id="call_1", name="submit_findings", args=good_args)],
            usage=Usage(1, 1),
            stop_reason="tool_use",
        )

    def cost_usd(self, usage: Usage) -> Decimal:
        return Decimal("0.0001")


def test_process_message_creates_incident() -> None:
    session = make_session()
    process_message(session, FIRING_RAW, [], _FakeLLMClient())  # type: ignore[arg-type]
    session.commit()
    rows = session.query(Incident).all()
    assert len(rows) == 1
    assert rows[0].status == "received"


def test_process_message_duplicate_does_not_create_second_row() -> None:
    session = make_session()
    process_message(session, FIRING_RAW, [], _FakeLLMClient())  # type: ignore[arg-type]
    session.commit()
    process_message(session, DUPLICATE_RAW, [], _FakeLLMClient())  # type: ignore[arg-type]
    session.commit()
    rows = session.query(Incident).all()
    assert len(rows) == 1


def test_process_message_malformed_does_not_raise() -> None:
    session = make_session()
    process_message(session, MALFORMED_RAW, [], _FakeLLMClient())  # type: ignore[arg-type]
    session.commit()
    assert session.query(Incident).count() == 0


def test_agent_main_module_imports_without_live_broker() -> None:
    import agent.main  # noqa: F401
