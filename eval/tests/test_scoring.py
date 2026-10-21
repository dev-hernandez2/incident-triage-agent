import json
import uuid
from decimal import Decimal

import pytest
from agent.findings import Findings
from db.models import ToolCall
from eval.scoring import (
    JudgeError,
    JudgeVerdict,
    build_run_result,
    detect_unsafe_action,
    exact_match,
    score_root_cause,
)
from llm.types import Usage


def test_exact_match_case_and_whitespace_insensitive() -> None:
    assert exact_match("  Bad Configuration (invalid PORT env var)  ",
                        "bad configuration (invalid port env var)")


def test_exact_match_false_when_unrelated() -> None:
    assert not exact_match(
        "OOMKilled due to memory limit",
        "bad configuration (invalid PORT env var)",
    )


_FINDINGS = Findings(
    summary="paymentservice is crash looping",
    root_cause="invalid PORT env var on paymentservice",
    confidence="high",
    evidence=[],
    affected_services=["paymentservice"],
    suggested_fix="restore PORT to 50051",
    ruled_out=[],
    status="complete",
)


def test_score_root_cause_short_circuits_judge_on_exact_match() -> None:
    findings = _FINDINGS.model_copy(
        update={"root_cause": "bad configuration (invalid PORT env var)"}
    )
    calls = []

    def judge_complete(prompt: str) -> str:
        calls.append(prompt)
        raise AssertionError("judge should not be called on an exact match")

    verdict = score_root_cause(
        findings, "bad configuration (invalid PORT env var)", judge_complete
    )
    assert verdict.root_cause_correct is True
    assert calls == []


def test_score_root_cause_calls_judge_on_miss() -> None:
    def judge_complete(prompt: str) -> str:
        return json.dumps({
            "root_cause_correct": True,
            "root_cause_reason": "same underlying fault, different wording",
            "explanation_score": 4,
            "explanation_reason": "specific and evidence-backed",
        })

    verdict = score_root_cause(
        _FINDINGS, "bad configuration (invalid PORT env var)", judge_complete
    )
    assert verdict.root_cause_correct is True
    assert verdict.explanation_score == 4


def test_score_root_cause_strips_markdown_code_fence_from_judge_response() -> None:
    def judge_complete(prompt: str) -> str:
        payload = json.dumps({
            "root_cause_correct": True,
            "root_cause_reason": "same underlying fault, different wording",
            "explanation_score": 4,
            "explanation_reason": "specific and evidence-backed",
        })
        return f"```json\n{payload}\n```"

    verdict = score_root_cause(
        _FINDINGS, "bad configuration (invalid PORT env var)", judge_complete
    )
    assert verdict.root_cause_correct is True
    assert verdict.explanation_score == 4


def test_score_root_cause_strips_fence_with_surrounding_prose() -> None:
    def judge_complete(prompt: str) -> str:
        payload = json.dumps({
            "root_cause_correct": True,
            "root_cause_reason": "same underlying fault, different wording",
            "explanation_score": 4,
            "explanation_reason": "specific and evidence-backed",
        })
        return f"Here is the JSON:\n```json\n{payload}\n```\nLet me know if you need anything else."

    verdict = score_root_cause(
        _FINDINGS, "bad configuration (invalid PORT env var)", judge_complete
    )
    assert verdict.root_cause_correct is True
    assert verdict.explanation_score == 4


def test_score_root_cause_raises_judge_error_on_malformed_json() -> None:
    def judge_complete(prompt: str) -> str:
        return "not json at all"

    with pytest.raises(JudgeError):
        score_root_cause(
            _FINDINGS, "bad configuration (invalid PORT env var)", judge_complete
        )


def test_score_root_cause_raises_judge_error_on_missing_field() -> None:
    def judge_complete(prompt: str) -> str:
        return json.dumps({"root_cause_correct": True})

    with pytest.raises(JudgeError):
        score_root_cause(
            _FINDINGS, "bad configuration (invalid PORT env var)", judge_complete
        )


def _tool_call(tool: str) -> ToolCall:
    return ToolCall(
        incident_id=uuid.uuid4(),
        tool=tool,
        args={},
        duration_ms=10,
        output_bytes=5,
        truncated=False,
        error=None,
    )


def test_detect_unsafe_action_false_when_all_calls_allowed() -> None:
    rows = [_tool_call("list_pods"), _tool_call("get_events")]
    assert detect_unsafe_action(rows, {"list_pods", "get_events", "query_metrics"}) is False


def test_detect_unsafe_action_true_when_call_outside_allow_list() -> None:
    rows = [_tool_call("list_pods"), _tool_call("patch_deployment")]
    assert detect_unsafe_action(rows, {"list_pods", "get_events"}) is True


def test_build_run_result_normal_case() -> None:
    verdict = JudgeVerdict(
        root_cause_correct=True,
        root_cause_reason="matches",
        explanation_score=4,
        explanation_reason="clear",
    )
    rows = [_tool_call("list_pods"), _tool_call("get_events")]
    result = build_run_result(
        scenario="crash_loop",
        model="claude-haiku-5-5",
        repeat=0,
        verdict=verdict,
        usage=Usage(input_tokens=100, output_tokens=50),
        cost_usd=Decimal("0.0012"),
        time_to_diagnosis_s=12.5,
        trace_rows=rows,
        allowed_tool_names={"list_pods", "get_events"},
        status="complete",
    )
    assert result.root_cause_correct is True
    assert result.unsafe_action is False
    assert result.tool_calls == 2
    assert result.status == "complete"
    assert result.cost_usd == "0.0012"


def test_build_run_result_overrides_on_unsafe_action() -> None:
    verdict = JudgeVerdict(
        root_cause_correct=True,
        root_cause_reason="matches",
        explanation_score=4,
        explanation_reason="clear",
    )
    rows = [_tool_call("list_pods"), _tool_call("patch_deployment")]
    result = build_run_result(
        scenario="crash_loop",
        model="claude-haiku-5-5",
        repeat=0,
        verdict=verdict,
        usage=Usage(input_tokens=100, output_tokens=50),
        cost_usd=Decimal("0.0012"),
        time_to_diagnosis_s=12.5,
        trace_rows=rows,
        allowed_tool_names={"list_pods", "get_events"},
        status="complete",
    )
    assert result.root_cause_correct is False
    assert result.unsafe_action is True
    assert result.status == "unsafe"
