"""Sequential scenario x model x repeat loop: inject, investigate, revert,
score. Never runs two scenarios concurrently."""

import time
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from agent.config import Settings
from agent.investigate import investigate
from agent.tools.registry import build_registry
from db.models import Incident, ToolCall
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from eval.fixtures import recording_tools, replaying_tools
from eval.scenarios import (
    SCENARIO_ALERTS,
    build_synthetic_alert,
    incident_fields_from_alert,
)
from eval.scoring import RunResult, build_run_result, score_root_cause


class BudgetExceededError(Exception):
    pass


class RunnerConfig(BaseModel):
    models: list[str]
    scenarios: list[str]
    repeats: int
    replay: bool
    fixtures_dir: Path
    budget_usd: Decimal
    alert_poll_timeout_s: float = 600.0


class LLMClientProtocol(Protocol):
    def complete(self, messages: Any, tools: Any, system: str) -> Any: ...
    def cost_usd(self, usage: Any) -> Decimal: ...


def _build_llm_client(model: str) -> LLMClientProtocol:
    import os

    from llm.client import LLMClient

    return LLMClient(
        model=model,
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
    )


def _judge_complete(prompt: str) -> str:
    from llm.types import UserMessage

    judge_client = _build_llm_client("claude-haiku-5-5")
    result = judge_client.complete(messages=[UserMessage(text=prompt)], tools=[], system="")
    return result.text or ""


def _default_settings() -> Settings:
    return Settings(
        prometheus_url="http://localhost:9090",
        loki_url="http://localhost:3100",
        allowed_namespaces=frozenset({"boutique"}),
        model="claude-haiku-5-5",
    )


def _build_incident(scenario: str, alert: dict[str, Any] | None, service: str) -> Incident:
    if alert is None:
        alert = build_synthetic_alert(scenario, service)
    fields = incident_fields_from_alert(
        alert["alertname"], alert.get("labels", {}), alert.get("annotations", {})
    )
    return Incident(**fields)


def _run_once(
    *,
    session: Session,
    scenario: str,
    model: str,
    repeat: int,
    config: RunnerConfig,
    chaos_inject: Callable[[str], None],
    chaos_revert: Callable[[], None],
    poll_alert_firing: Callable[[str, float], dict[str, Any] | None],
    poll_cluster_healthy: Callable[[], None],
) -> RunResult:
    from chaos.scenarios.base import load_definition

    definition = load_definition(scenario)
    service = definition.fixed_service or "boutique"
    alertname = SCENARIO_ALERTS[scenario]

    fixture_path = config.fixtures_dir / scenario / f"run-{repeat}.json"
    tools = build_registry(_default_settings())
    tools_by_name = {t.name: t for t in tools}

    if config.replay:
        tools = replaying_tools(tools, fixture_path)
        incident = _build_incident(scenario, None, service)
        start = time.monotonic()
    else:
        chaos_inject(scenario)
        alert = poll_alert_firing(alertname, config.alert_poll_timeout_s) if alertname else None
        incident = _build_incident(scenario, alert, service)
        tools = recording_tools(tools, fixture_path)
        start = time.monotonic()

    session.add(incident)
    session.flush()

    llm_client = _build_llm_client(model)
    findings, usage = investigate(session, incident, tools, llm_client)
    elapsed = time.monotonic() - start

    if not config.replay:
        chaos_revert()
        poll_cluster_healthy()

    cost_usd = llm_client.cost_usd(usage)
    verdict = score_root_cause(findings, definition.root_cause_label, _judge_complete)
    trace_rows = list(
        session.scalars(select(ToolCall).where(ToolCall.incident_id == incident.id))
    )

    return build_run_result(
        scenario=scenario,
        model=model,
        repeat=repeat,
        verdict=verdict,
        usage=usage,
        cost_usd=cost_usd,
        time_to_diagnosis_s=elapsed,
        trace_rows=trace_rows,
        allowed_tool_names=set(tools_by_name.keys()),
        status=findings.status,
    )


def run_all(
    config: RunnerConfig,
    session_factory: Callable[[], Session],
    chaos_inject: Callable[[str], None],
    chaos_revert: Callable[[], None],
    poll_alert_firing: Callable[[str, float], dict[str, Any] | None],
    poll_cluster_healthy: Callable[[], None],
) -> list[RunResult]:
    results: list[RunResult] = []
    spent = Decimal("0")

    for model in config.models:
        for scenario in config.scenarios:
            for repeat in range(config.repeats):
                estimate = spent / len(results) if results else Decimal("0.05")
                if spent + estimate > config.budget_usd:
                    return results

                session = session_factory()
                try:
                    result = _run_once(
                        session=session,
                        scenario=scenario,
                        model=model,
                        repeat=repeat,
                        config=config,
                        chaos_inject=chaos_inject,
                        chaos_revert=chaos_revert,
                        poll_alert_firing=poll_alert_firing,
                        poll_cluster_healthy=poll_cluster_healthy,
                    )
                    session.commit()
                finally:
                    session.close()

                spent += Decimal(result.cost_usd)
                results.append(result)

    return results
