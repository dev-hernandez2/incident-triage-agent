import json

import pytest
from agent.findings import Findings
from eval.scoring import JudgeError, exact_match, score_root_cause


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
