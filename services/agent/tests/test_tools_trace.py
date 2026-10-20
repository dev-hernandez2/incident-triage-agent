"""Every tool call shows up as a row in tool_calls."""

import uuid

from agent.tools.base import ToolResult
from agent.tools.trace import record_tool_call
from db.models import Base, ToolCall
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _register_gen_random_uuid(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
        dbapi_connection.create_function("gen_random_uuid", 0, lambda: uuid.uuid4().hex)

    Base.metadata.create_all(engine)
    return Session(engine)


def test_successful_call_is_recorded() -> None:
    session = make_session()
    incident_id = uuid.uuid4()
    result = ToolResult(output="ok", truncated=False)

    record_tool_call(
        session, incident_id, "list_pods", {"namespace": "boutique"}, result, None, 42
    )
    session.commit()

    rows = session.query(ToolCall).all()
    assert len(rows) == 1
    assert rows[0].tool == "list_pods"
    assert rows[0].incident_id == incident_id
    assert rows[0].duration_ms == 42
    assert rows[0].output_bytes == 2
    assert rows[0].truncated is False
    assert rows[0].error is None


def test_failed_call_is_recorded_with_error() -> None:
    session = make_session()
    incident_id = uuid.uuid4()

    record_tool_call(
        session, incident_id, "get_events", {"namespace": "boutique"}, None, "timed out", 10
    )
    session.commit()

    row = session.query(ToolCall).one()
    assert row.error == "timed out"
    assert row.output_bytes == 0
