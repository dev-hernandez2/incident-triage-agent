import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from db.models import Base
from eval.runner import RunnerConfig, run_all
from llm.types import CompletionResult, Message, Usage
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session


def _make_session_factory(tmp_path: Path) -> Callable[[], Session]:
    import uuid

    engine = create_engine(f"sqlite:///{tmp_path}/test.db")

    @event.listens_for(engine, "connect")
    def _register_gen_random_uuid(dbapi_connection: Any, connection_record: Any) -> None:
        dbapi_connection.create_function("gen_random_uuid", 0, lambda: uuid.uuid4().hex)

    Base.metadata.create_all(engine)
    return lambda: Session(engine)


def test_run_all_replay_mode_runs_one_scenario_one_repeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture_dir = tmp_path / "fixtures"
    scenario_dir = fixture_dir / "crash_loop"
    scenario_dir.mkdir(parents=True)
    (scenario_dir / "run-0.json").write_text(json.dumps([
        {
            "index": 0,
            "tool": "list_pods",
            "args": {"namespace": "boutique", "selector": None},
            "output": (
                '[{"name": "paymentservice-abc", "phase": "Running", "ready": "0/1", '
                '"restarts": 5, "last_state": null}]'
            ),
        },
    ]))

    class _StubLLMClient:
        def complete(
            self, messages: list[Message], tools: list[dict[str, object]], system: str
        ) -> CompletionResult:
            from llm.types import AssistantMessage, ToolCallRequest, ToolResultMessage

            has_submitted = any(
                isinstance(m, AssistantMessage)
                and any(c.name == "submit_findings" for c in m.tool_calls)
                for m in messages
            )
            if has_submitted:
                raise AssertionError("should not be called again after submit_findings")

            has_tool_result = any(isinstance(m, ToolResultMessage) for m in messages)
            if not has_tool_result:
                return CompletionResult(
                    text=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="call_0",
                            name="list_pods",
                            args={"namespace": "boutique", "selector": None},
                        )
                    ],
                    usage=Usage(input_tokens=10, output_tokens=5),
                    stop_reason="tool_use",
                )

            return CompletionResult(
                text=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        name="submit_findings",
                        args={
                            "summary": "bad PORT env var",
                            "root_cause": "bad configuration (invalid PORT env var)",
                            "confidence": "high",
                            "evidence": [],
                            "affected_services": ["paymentservice"],
                            "suggested_fix": "restore PORT to 50051",
                            "ruled_out": [],
                        },
                    )
                ],
                usage=Usage(input_tokens=50, output_tokens=20),
                stop_reason="tool_use",
            )

        def cost_usd(self, usage: Usage) -> Decimal:
            return Decimal("0.001")

    monkeypatch.setattr("eval.runner._build_llm_client", lambda model: _StubLLMClient())
    monkeypatch.setattr("eval.runner._judge_complete", lambda prompt: json.dumps({
        "root_cause_correct": True, "root_cause_reason": "matches",
        "explanation_score": 5, "explanation_reason": "clear",
    }))

    config = RunnerConfig(
        models=["claude-haiku-5-5"],
        scenarios=["crash_loop"],
        repeats=1,
        replay=True,
        fixtures_dir=fixture_dir,
        budget_usd=Decimal("20"),
    )

    results = run_all(
        config,
        session_factory=_make_session_factory(tmp_path),
        chaos_inject=lambda scenario: None,
        chaos_revert=lambda: None,
        poll_alert_firing=lambda alertname, timeout: None,
        poll_cluster_healthy=lambda: None,
    )

    assert len(results) == 1
    assert results[0].scenario == "crash_loop"
    assert results[0].model == "claude-haiku-5-5"
    assert results[0].root_cause_correct is True


def test_run_all_stops_when_budget_exceeded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture_dir = tmp_path / "fixtures"
    for scenario in ("crash_loop", "oom"):
        scenario_dir = fixture_dir / scenario
        scenario_dir.mkdir(parents=True)
        (scenario_dir / "run-0.json").write_text(json.dumps([
            {
                "index": 0,
                "tool": "list_pods",
                "args": {"namespace": "boutique", "selector": None},
                "output": (
                    '[{"name": "x", "phase": "Running", "ready": "1/1", '
                    '"restarts": 0, "last_state": null}]'
                ),
            },
        ]))

    class _ExpensiveStubLLMClient:
        def complete(
            self, messages: list[Message], tools: list[dict[str, object]], system: str
        ) -> CompletionResult:
            from llm.types import ToolCallRequest

            return CompletionResult(
                text=None,
                tool_calls=[ToolCallRequest(id="c1", name="submit_findings", args={
                    "summary": "s", "root_cause": "unrelated cause", "confidence": "low",
                    "evidence": [], "affected_services": [], "suggested_fix": "f", "ruled_out": [],
                })],
                usage=Usage(input_tokens=1, output_tokens=1),
                stop_reason="tool_use",
            )

        def cost_usd(self, usage: Usage) -> Decimal:
            return Decimal("15")  # each run costs more than half the budget

    monkeypatch.setattr("eval.runner._build_llm_client", lambda model: _ExpensiveStubLLMClient())
    monkeypatch.setattr("eval.runner._judge_complete", lambda prompt: json.dumps({
        "root_cause_correct": False, "root_cause_reason": "no match",
        "explanation_score": 1, "explanation_reason": "vague",
    }))

    config = RunnerConfig(
        models=["claude-haiku-5-5"],
        scenarios=["crash_loop", "oom"],
        repeats=1,
        replay=True,
        fixtures_dir=fixture_dir,
        budget_usd=Decimal("20"),
    )

    results = run_all(
        config,
        session_factory=_make_session_factory(tmp_path),
        chaos_inject=lambda scenario: None,
        chaos_revert=lambda: None,
        poll_alert_firing=lambda alertname, timeout: None,
        poll_cluster_healthy=lambda: None,
    )

    # second run's projected cost (15) would push total (15+15=30) over budget (20)
    assert len(results) == 1
