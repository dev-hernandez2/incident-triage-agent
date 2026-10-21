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

    class _StubJudgeClient:
        def complete(
            self, messages: list[Message], tools: list[dict[str, object]], system: str
        ) -> CompletionResult:
            return CompletionResult(
                text=json.dumps({
                    "root_cause_correct": True, "root_cause_reason": "matches",
                    "explanation_score": 5, "explanation_reason": "clear",
                }),
                tool_calls=[],
                usage=Usage(input_tokens=0, output_tokens=0),
                stop_reason="end_turn",
            )

        def cost_usd(self, usage: Usage) -> Decimal:
            return Decimal("0")

    # _build_llm_client is called once for the model-under-test, then once
    # more (hardcoded "claude-haiku-5-5") to build the judge client, each
    # time _run_once runs. Alternate stubs by call order within each run.
    build_calls: list[str] = []

    def _fake_build_llm_client(model: str) -> Any:
        build_calls.append(model)
        is_judge_call = len(build_calls) % 2 == 0
        return _StubJudgeClient() if is_judge_call else _StubLLMClient()

    monkeypatch.setattr("eval.runner._build_llm_client", _fake_build_llm_client)

    config = RunnerConfig(
        models=["claude-haiku-5-5"],
        scenarios=["crash_loop"],
        repeats=5,
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

    class _FreeJudgeClient:
        def complete(
            self, messages: list[Message], tools: list[dict[str, object]], system: str
        ) -> CompletionResult:
            return CompletionResult(
                text=json.dumps({
                    "root_cause_correct": False, "root_cause_reason": "no match",
                    "explanation_score": 1, "explanation_reason": "vague",
                }),
                tool_calls=[],
                usage=Usage(input_tokens=0, output_tokens=0),
                stop_reason="end_turn",
            )

        def cost_usd(self, usage: Usage) -> Decimal:
            return Decimal("0")

    # _build_llm_client is called once for the model-under-test, then once
    # more for the judge, each time _run_once runs. Alternate by call order.
    build_calls: list[str] = []

    def _fake_build_llm_client(model: str) -> Any:
        build_calls.append(model)
        is_judge_call = len(build_calls) % 2 == 0
        return _FreeJudgeClient() if is_judge_call else _ExpensiveStubLLMClient()

    monkeypatch.setattr("eval.runner._build_llm_client", _fake_build_llm_client)

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


def test_run_all_isolates_exception_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run that raises mid-_run_once (e.g. a transient judge/API error)
    must not crash run_all and discard prior results. It should be caught,
    turned into a status="error" RunResult, and the loop should continue
    to subsequent scenarios/repeats."""
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

    class _OkStubLLMClient:
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
            return Decimal("0.001")

    class _BoomJudgeClient:
        def complete(
            self, messages: list[Message], tools: list[dict[str, object]], system: str
        ) -> CompletionResult:
            raise RuntimeError("judge API unavailable")

        def cost_usd(self, usage: Usage) -> Decimal:
            return Decimal("0")

    # First scenario (crash_loop) processed first alphabetically-independent
    # ordering follows config.scenarios list order: crash_loop, then oom.
    # Make the judge blow up only on the first run so we can confirm the
    # loop both records an error result AND continues to the second run.
    call_count = {"n": 0}

    def _fake_build_llm_client(model: str) -> Any:
        call_count["n"] += 1
        is_judge_call = call_count["n"] % 2 == 0
        if is_judge_call:
            # Only the first judge call fails; subsequent ones succeed.
            if call_count["n"] == 2:
                return _BoomJudgeClient()

            class _OkJudgeClient:
                def complete(
                    self, messages: list[Message], tools: list[dict[str, object]], system: str
                ) -> CompletionResult:
                    return CompletionResult(
                        text=json.dumps({
                            "root_cause_correct": False, "root_cause_reason": "no match",
                            "explanation_score": 1, "explanation_reason": "vague",
                        }),
                        tool_calls=[],
                        usage=Usage(input_tokens=0, output_tokens=0),
                        stop_reason="end_turn",
                    )

                def cost_usd(self, usage: Usage) -> Decimal:
                    return Decimal("0")

            return _OkJudgeClient()
        return _OkStubLLMClient()

    monkeypatch.setattr("eval.runner._build_llm_client", _fake_build_llm_client)

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

    assert len(results) == 2
    assert results[0].scenario == "crash_loop"
    assert results[0].status == "error"
    assert results[0].root_cause_correct is False
    assert results[1].scenario == "oom"
    assert results[1].status != "error"


def test_judge_cost_is_added_to_run_result_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The judge call's Usage/cost must be reflected in RunResult.cost_usd,
    not just the model-under-test's cost (Finding 3)."""
    fixture_dir = tmp_path / "fixtures"
    scenario_dir = fixture_dir / "crash_loop"
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

    class _StubLLMClient:
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
                usage=Usage(input_tokens=100, output_tokens=50),
                stop_reason="tool_use",
            )

        def cost_usd(self, usage: Usage) -> Decimal:
            # $0.01 per input token + $0.02 per output token, deterministic stub
            return Decimal(usage.input_tokens) * Decimal("0.01") + Decimal(
                usage.output_tokens
            ) * Decimal("0.02")

    class _StubJudgeClient:
        def complete(
            self, messages: list[Message], tools: list[dict[str, object]], system: str
        ) -> CompletionResult:
            return CompletionResult(
                text=json.dumps({
                    "root_cause_correct": False, "root_cause_reason": "no match",
                    "explanation_score": 1, "explanation_reason": "vague",
                }),
                tool_calls=[],
                usage=Usage(input_tokens=200, output_tokens=10),
                stop_reason="end_turn",
            )

        def cost_usd(self, usage: Usage) -> Decimal:
            # distinct pricing so main-model cost and judge cost are
            # distinguishable in the assertion below
            return Decimal(usage.input_tokens) * Decimal("0.001") + Decimal(
                usage.output_tokens
            ) * Decimal("0.002")

    build_calls: list[str] = []

    def _fake_build_llm_client(model: str) -> Any:
        build_calls.append(model)
        is_judge_call = len(build_calls) % 2 == 0
        return _StubJudgeClient() if is_judge_call else _StubLLMClient()

    monkeypatch.setattr("eval.runner._build_llm_client", _fake_build_llm_client)

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
    main_model_cost = Decimal("100") * Decimal("0.01") + Decimal("50") * Decimal("0.02")
    judge_cost = Decimal("200") * Decimal("0.001") + Decimal("10") * Decimal("0.002")
    expected_total = main_model_cost + judge_cost

    assert Decimal(results[0].cost_usd) == expected_total
    # sanity: judge cost actually contributes (i.e. this test would fail
    # before the Finding 3 fix, when judge cost was discarded)
    assert Decimal(results[0].cost_usd) != main_model_cost
