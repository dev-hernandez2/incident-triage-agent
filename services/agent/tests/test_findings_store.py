import uuid
from decimal import Decimal

from agent.findings import Evidence, Findings, ManualAction
from agent.findings_store import save_finding
from db.models import Base, Finding, Incident
from llm.types import Usage
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _register_gen_random_uuid(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
        dbapi_connection.create_function("gen_random_uuid", 0, lambda: uuid.uuid4().hex)

    Base.metadata.create_all(engine)
    return Session(engine)


def test_save_finding_persists_all_fields() -> None:
    session = make_session()
    incident = Incident(
        fingerprint="fp1", alertname="BoutiquePodCrashLooping", labels={}, status="received"
    )
    session.add(incident)
    session.flush()

    findings = Findings(
        summary="cartservice crash-looping",
        root_cause="missing REDIS_ADDR",
        confidence="high",
        evidence=[Evidence(tool_call_id="abc", detail="pod event")],
        affected_services=["cartservice"],
        suggested_fix=ManualAction(type="manual", reason="set REDIS_ADDR"),
        ruled_out=[],
        status="complete",
    )

    row = save_finding(
        session, incident, findings, Usage(input_tokens=100, output_tokens=50), Decimal("0.0123")
    )
    session.commit()

    fetched = session.query(Finding).one()
    assert fetched.id == row.id
    assert fetched.incident_id == incident.id
    assert fetched.root_cause == "missing REDIS_ADDR"
    assert fetched.evidence == [{"tool_call_id": "abc", "detail": "pod event"}]
    assert fetched.suggested_fix == {"type": "manual", "reason": "set REDIS_ADDR"}
    assert fetched.input_tokens == 100
    assert fetched.output_tokens == 50
    assert fetched.cost_usd == Decimal("0.0123")
    assert fetched.posted_at is None
