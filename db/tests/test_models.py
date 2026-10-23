"""Tests for the Incident model's table/index definition."""

from decimal import Decimal

from db.models import Action, AuditLog, Finding, Incident
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


def test_incident_annotations_round_trips_as_a_jsonb_dict(session: Session) -> None:
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


def test_finding_row_round_trips_with_jsonb_fields(session: Session) -> None:
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


def test_finding_suggested_fix_accepts_structured_action(session: Session) -> None:
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


def test_action_lifecycle_columns(session: Session) -> None:
    incident = Incident(
        fingerprint="fp-2", alertname="PodCrashLooping", labels={}, status="received"
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

    action = Action(
        incident_id=incident.id,
        finding_id=finding.id,
        type="rollback",
        deployment="cartservice",
        replicas=None,
        reason="bad deploy",
        status="pending",
    )
    session.add(action)
    session.flush()
    session.refresh(action)

    assert action.status == "pending"
    assert action.approved_by is None
    assert action.created_at is not None


def test_audit_log_detail_is_jsonb(session: Session) -> None:
    incident = Incident(
        fingerprint="fp-3", alertname="PodCrashLooping", labels={}, status="received"
    )
    session.add(incident)
    session.flush()

    entry = AuditLog(
        incident_id=incident.id,
        actor="agent",
        event_type="tool_call",
        detail={"tool": "describe_pod", "duration_ms": 120},
    )
    session.add(entry)
    session.flush()
    session.refresh(entry)

    assert entry.detail == {"tool": "describe_pod", "duration_ms": 120}
    assert entry.created_at is not None
