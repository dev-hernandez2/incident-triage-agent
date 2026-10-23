"""Tests for the Incident model's table/index definition."""

import uuid
from decimal import Decimal

from db.models import Base, Finding, Incident
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session


def test_incident_tablename() -> None:
    assert Incident.__tablename__ == "incidents"


def test_incident_columns() -> None:
    columns = {c.name for c in Incident.__table__.columns}
    assert columns == {
        "id",
        "fingerprint",
        "alertname",
        "labels",
        "annotations",
        "status",
        "created_at",
    }


def test_incident_has_partial_unique_index_on_fingerprint() -> None:
    indexes = Incident.__table__.indexes  # type: ignore[attr-defined]
    fingerprint_indexes = [ix for ix in indexes if "fingerprint" in [c.name for c in ix.columns]]
    assert len(fingerprint_indexes) == 1
    index = fingerprint_indexes[0]
    assert index.unique is True
    assert index.dialect_options["postgresql"]["where"] is not None


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _register_gen_random_uuid(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
        dbapi_connection.create_function("gen_random_uuid", 0, lambda: uuid.uuid4().hex)

    Base.metadata.create_all(engine)
    return Session(engine)


def test_incident_annotations_round_trips_as_a_jsonb_dict() -> None:
    session = make_session()
    incident = Incident(
        fingerprint="fp-annotations",
        alertname="BoutiquePodCrashLooping",
        labels={},
        annotations={"summary": "cartservice is restarting repeatedly"},
        status="received",
    )
    session.add(incident)
    session.commit()

    row = session.query(Incident).filter_by(fingerprint="fp-annotations").one()
    assert row.annotations == {"summary": "cartservice is restarting repeatedly"}


def test_finding_row_round_trips_with_jsonb_fields() -> None:
    session = make_session()
    incident = Incident(
        fingerprint="fp1", alertname="BoutiquePodCrashLooping", labels={}, status="received"
    )
    session.add(incident)
    session.flush()

    finding = Finding(
        incident_id=incident.id,
        summary="cartservice crash-looping",
        root_cause="missing REDIS_ADDR",
        confidence="high",
        evidence=[{"tool_call_id": "abc", "detail": "pod event"}],
        affected_services=["cartservice"],
        suggested_fix={"type": "manual", "reason": "set REDIS_ADDR"},
        ruled_out=[],
        status="complete",
        input_tokens=100,
        output_tokens=50,
        cost_usd=Decimal("0.01"),
    )
    session.add(finding)
    session.commit()

    row = session.query(Finding).one()
    assert row.evidence == [{"tool_call_id": "abc", "detail": "pod event"}]
    assert row.posted_at is None
    assert row.cost_usd == Decimal("0.01")


def test_finding_suggested_fix_accepts_structured_action() -> None:
    session = make_session()
    incident = Incident(
        fingerprint="fp-1", alertname="PodCrashLooping", labels={}, status="received"
    )
    session.add(incident)
    session.flush()

    finding = Finding(
        incident_id=incident.id,
        summary="s",
        root_cause="r",
        confidence="high",
        evidence=[],
        affected_services=[],
        suggested_fix={"type": "rollback", "deployment": "cartservice", "reason": "bad deploy"},
        ruled_out=[],
        status="complete",
        input_tokens=1,
        output_tokens=1,
        cost_usd=Decimal("0.01"),
    )
    session.add(finding)
    session.flush()
    session.refresh(finding)

    assert finding.suggested_fix == {
        "type": "rollback",
        "deployment": "cartservice",
        "reason": "bad deploy",
    }
