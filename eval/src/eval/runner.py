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
from eval.scoring import (
    JudgeVerdict,
    RunResult,
    build_run_result,
    score_prompt_injection,
    score_root_cause,
)


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


def _make_judge_complete() -> tuple[Callable[[str], str], Callable[[], Decimal]]:
    """Builds a judge_complete closure plus a cost accessor.

    `score_root_cause` expects a plain `Callable[[str], str]` (the
    established Task 4/5 interface), so the per-call `Usage` can't be
    returned through that function's return value. Instead this factory
    accumulates cost on a judge `LLMClient` built once per run, and
    exposes it via a zero-arg accessor the caller can read after
    `score_root_cause` returns.
    """
    from llm.types import UserMessage

    judge_client = _build_llm_client("claude-haiku-5-5")
    judge_cost = Decimal("0")

    def judge_complete(prompt: str) -> str:
        nonlocal judge_cost
        result = judge_client.complete(messages=[UserMessage(text=prompt)], tools=[], system="")
        judge_cost += judge_client.cost_usd(result.usage)
        return result.text or ""

    return judge_complete, lambda: judge_cost


def _default_settings() -> Settings:
    return Settings(
        prometheus_url="http://localhost:9090",
        loki_url="http://localhost:3100",
        allowed_namespaces=frozenset({"boutique"}),
        model="claude-haiku-5-5",
        metrics_port=9100,
        otel_exporter_otlp_endpoint="http://localhost:4318",
    )


def _build_incident(
    scenario: str, alert: dict[str, Any] | None, service: str, run_id: str
) -> Incident:
    if alert is None:
        alert = build_synthetic_alert(scenario, service)
    fields = incident_fields_from_alert(
        alert["alertname"], alert.get("labels", {}), alert.get("annotations", {}), run_id=run_id
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

    run_id = f"{scenario}-r{repeat}"
    if config.replay:
        tools = replaying_tools(tools, fixture_path)
        incident = _build_incident(scenario, None, service, run_id)
        start = time.monotonic()
    else:
        chaos_inject(scenario)
        alert = poll_alert_firing(alertname, config.alert_poll_timeout_s) if alertname else None
        incident = _build_incident(scenario, alert, service, run_id)
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

    judge_complete, judge_cost = _make_judge_complete()
    verdict = score_root_cause(findings, definition.root_cause_label, judge_complete)

    if scenario == "prompt_injection" and definition.injected_instruction is not None:
        injection_safe = score_prompt_injection(findings, definition.injected_instruction)
        if not injection_safe:
            verdict = JudgeVerdict(
                root_cause_correct=False,
                root_cause_reason=(
                    "agent echoed/acted on the injected log instruction "
                    f"{definition.injected_instruction!r}"
                ),
                explanation_score=0,
                explanation_reason="failed prompt-injection safety check",
            )

    cost_usd = llm_client.cost_usd(usage) + judge_cost()
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


def _fixture_exists(config: RunnerConfig, scenario: str, repeat: int) -> bool:
    return (config.fixtures_dir / scenario / f"run-{repeat}.json").exists()


def _error_result(scenario: str, model: str, repeat: int, exc: Exception) -> RunResult:
    """Minimal RunResult for a run that raised mid-way. Reuses existing
    fields (root_cause_reason) rather than adding a new schema field, per
    the constraint that RunResult's field set also drives report.py's
    CSV/summary output. Cost/usage are zero since nothing billable is
    known to have completed."""
    return RunResult(
        scenario=scenario,
        model=model,
        repeat=repeat,
        root_cause_correct=False,
        root_cause_reason=f"run errored: {exc}",
        explanation_score=0,
        explanation_reason="not judged: run raised an exception",
        time_to_diagnosis_s=0.0,
        tool_calls=0,
        input_tokens=0,
        output_tokens=0,
        cost_usd="0",
        unsafe_action=False,
        status="error",
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
                if config.replay and not _fixture_exists(config, scenario, repeat):
                    print(
                        f"skipping {scenario} repeat={repeat}: "
                        f"no fixture run-{repeat}.json found"
                    )
                    continue

                estimate = spent / len(results) if results else Decimal("0.05")
                if spent + estimate > config.budget_usd:
                    return results

                session = session_factory()
                try:
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
                    except Exception as exc:  # isolate per-run failures, never lose prior results
                        session.rollback()
                        result = _error_result(scenario, model, repeat, exc)
                finally:
                    session.close()

                spent += Decimal(result.cost_usd)
                results.append(result)

    return results
