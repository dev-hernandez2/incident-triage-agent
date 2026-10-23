"""Kafka consumer: alerts.raw -> incidents table -> investigation -> findings table.

No agent framework (LangGraph, CrewAI, etc.) — see docs/adr/0001-agent-framework.md.
Model is a config value, not hardcoded.
"""

import os
from collections.abc import Callable
from typing import TYPE_CHECKING

from db.engine import engine_from_env
from db.models import Incident
from db.session import session_scope
from llm.client import LLMClient
from obs.logging import configure_logging
from obs.metrics import start_metrics_server
from obs.tracing import configure_tracing
from sqlalchemy.orm import Session

from agent.config import load_settings
from agent.findings_store import save_finding
from agent.incidents import upsert_incident
from agent.investigate import investigate
from agent.messages import parse_alert_message
from agent.tools.base import ToolSpec
from agent.tools.registry import build_registry

if TYPE_CHECKING:
    from confluent_kafka import Consumer

logger = configure_logging("agent")


def run_investigation(
    session: Session, incident: Incident, tools: list[ToolSpec], llm_client: LLMClient
) -> None:
    logger.info("investigating", extra={"incident_id": str(incident.id)})
    findings, usage = investigate(session, incident, tools, llm_client)
    cost = llm_client.cost_usd(usage)
    save_finding(session, incident, findings, usage, cost)
    logger.info(
        "investigation complete",
        extra={"incident_id": str(incident.id), "status": findings.status, "cost_usd": str(cost)},
    )


def process_message(
    session: Session, raw: bytes, tools: list[ToolSpec], llm_client: LLMClient
) -> None:
    try:
        message = parse_alert_message(raw)
    except ValueError as exc:
        logger.warning("skipping unparseable message", extra={"error": str(exc)})
        return

    incident = upsert_incident(session, message)
    if incident is not None and incident.status == "received":
        try:
            run_investigation(session, incident, tools, llm_client)
        except Exception:
            logger.exception(
                "investigation failed, incident left without a finding for reprocessing",
                extra={"incident_id": str(incident.id)},
            )


def consume_forever(
    consumer: "Consumer",
    session_factory: Callable[[], Session],
    tools: list[ToolSpec],
    llm_client: LLMClient,
) -> None:
    while True:
        msg = consumer.poll(timeout=1.0)
        if msg is None:
            continue
        if msg.error():
            logger.error("kafka error", extra={"error": str(msg.error())})
            continue
        raw = msg.value()
        if raw is None:
            logger.warning("skipping message with no payload")
            continue
        with session_scope(session_factory) as session:
            process_message(session, raw, tools, llm_client)
        consumer.commit(message=msg, asynchronous=False)


def main() -> None:
    from confluent_kafka import Consumer

    bootstrap_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap_servers,
            "group.id": "triage-agent",
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe(["alerts.raw"])

    engine = engine_from_env()
    session_factory = lambda: Session(engine)  # noqa: E731

    settings = load_settings()
    start_metrics_server(settings.metrics_port)
    configure_tracing("triage-agent", settings.otel_exporter_otlp_endpoint)
    tools = build_registry(settings)
    llm_client = LLMClient(
        model=settings.model,
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
    )

    consume_forever(consumer, session_factory, tools, llm_client)


if __name__ == "__main__":
    main()
