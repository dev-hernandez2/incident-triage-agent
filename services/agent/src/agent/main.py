"""Kafka consumer: alerts.raw -> incidents table, then a stub investigation.

No agent framework (LangGraph, CrewAI, etc.) — see docs/adr/0001-agent-framework.md.
Model is a config value, not hardcoded.
"""

import os
from collections.abc import Callable
from typing import TYPE_CHECKING

from db.models import Incident
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from agent.incidents import upsert_incident
from agent.logging_config import configure_logging
from agent.messages import parse_alert_message

if TYPE_CHECKING:
    from confluent_kafka import Consumer

logger = configure_logging()


def run_investigation(incident: Incident) -> str:
    logger.info(
        "would investigate",
        extra={"incident_id": str(incident.id)},
    )
    return "stub: investigation not yet implemented"


def process_message(session: Session, raw: bytes) -> None:
    try:
        message = parse_alert_message(raw)
    except ValueError as exc:
        logger.warning("skipping unparseable message", extra={"error": str(exc)})
        return

    incident = upsert_incident(session, message)
    if incident is not None and incident.status == "received":
        run_investigation(incident)


def consume_forever(consumer: "Consumer", session_factory: Callable[[], Session]) -> None:
    while True:
        msg = consumer.poll(timeout=1.0)
        if msg is None:
            continue
        if msg.error():
            logger.error("kafka error", extra={"error": str(msg.error())})
            continue
        raw = msg.value()
        if raw is None:
            continue
        session = session_factory()
        try:
            process_message(session, raw)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
        consumer.commit(message=msg, asynchronous=False)


def main() -> None:
    from confluent_kafka import Consumer

    bootstrap_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    database_url = os.environ.get("DATABASE_URL", "postgresql://triage:triage@localhost:5432/triage")

    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap_servers,
            "group.id": "triage-agent",
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe(["alerts.raw"])

    engine = create_engine(database_url)
    session_factory = lambda: Session(engine)  # noqa: E731

    consume_forever(consumer, session_factory)


if __name__ == "__main__":
    main()
