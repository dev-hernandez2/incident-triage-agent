import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from bot.main import fetch_unposted_findings, mark_posted, post_findings
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
        suggested_fix='{"type": "manual", "reason": "x"}',
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
    _make_finding(session, posted_at=datetime.now(UTC))
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


class _FakeChannel:
    def __init__(self, fail_on: set[int] | None = None) -> None:
        self.sent: list[object] = []
        self._fail_on = fail_on or set()
        self._calls = 0

    async def send(self, embed: object) -> None:
        call_index = self._calls
        self._calls += 1
        if call_index in self._fail_on:
            raise RuntimeError("simulated Discord API failure")
        self.sent.append(embed)


def test_post_findings_marks_every_row_posted() -> None:
    session = make_session()
    _make_finding(session, posted_at=None)
    _make_finding(session, posted_at=None)
    session.commit()
    channel = _FakeChannel()

    asyncio.run(post_findings(session, channel))  # type: ignore[arg-type]

    assert len(channel.sent) == 2
    assert fetch_unposted_findings(session) == []


def test_post_findings_skips_a_failing_row_and_still_posts_the_rest() -> None:
    session = make_session()
    _make_finding(session, posted_at=None)
    _make_finding(session, posted_at=None)
    session.commit()
    channel = _FakeChannel(fail_on={0})

    asyncio.run(post_findings(session, channel))  # type: ignore[arg-type]

    assert len(channel.sent) == 1
    assert len(fetch_unposted_findings(session)) == 1
