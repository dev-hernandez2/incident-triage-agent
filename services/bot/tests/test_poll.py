import uuid
from datetime import datetime, timezone
from decimal import Decimal

from bot.main import fetch_unposted_findings, mark_posted
from db.models import Base, Finding, Incident
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _register_gen_random_uuid(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
        dbapi_connection.create_function("gen_random_uuid", 0, lambda: uuid.uuid4().hex)

    Base.metadata.create_all(engine)
    return Session(engine)


def _make_finding(session: Session, posted_at: datetime | None) -> Finding:
    incident = Incident(fingerprint=str(uuid.uuid4()), alertname="x", labels={}, status="received")
    session.add(incident)
    session.flush()
    finding = Finding(
        incident_id=incident.id,
        summary="x",
        root_cause="x",
        confidence="low",
        evidence=[],
        affected_services=[],
        suggested_fix="x",
        ruled_out=[],
        status="complete",
        input_tokens=1,
        output_tokens=1,
        cost_usd=Decimal("0.001"),
        posted_at=posted_at,
    )
    session.add(finding)
    session.flush()
    return finding


def test_fetch_unposted_findings_returns_only_rows_with_null_posted_at() -> None:
    session = make_session()
    unposted = _make_finding(session, posted_at=None)
    _make_finding(session, posted_at=datetime.now(timezone.utc))
    session.commit()

    results = fetch_unposted_findings(session)

    assert [f.id for f in results] == [unposted.id]


def test_mark_posted_sets_posted_at() -> None:
    session = make_session()
    finding = _make_finding(session, posted_at=None)
    session.commit()

    mark_posted(session, finding)
    session.commit()

    refreshed = session.query(Finding).filter_by(id=finding.id).one()
    assert refreshed.posted_at is not None
