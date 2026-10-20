"""Tests for baseline root-cause analysis functions."""

from eval.baselines import llm_no_tools_root_cause, rule_based_root_cause
from llm.types import CompletionResult, Message, Usage

_EVENTS = [
    {
        "type": "Normal",
        "reason": "Scheduled",
        "message": "Successfully assigned",
        "count": 1,
        "first_timestamp": "2026-10-19T10:00:00Z",
        "last_timestamp": "2026-10-19T10:00:00Z",
        "involved_object": {"kind": "Pod", "name": "paymentservice-abc"},
    },
    {
        "type": "Warning",
        "reason": "BackOff",
        "message": "Back-off restarting failed container",
        "count": 5,
        "first_timestamp": "2026-10-19T10:01:00Z",
        "last_timestamp": "2026-10-19T10:05:00Z",
        "involved_object": {"kind": "Pod", "name": "paymentservice-abc"},
    },
]


def test_rule_based_root_cause_picks_most_recent_change_event() -> None:
    findings = rule_based_root_cause(_EVENTS)
    assert "paymentservice-abc" in findings.root_cause
    assert findings.confidence == "low"
    assert findings.status == "complete"


def test_rule_based_root_cause_handles_no_matching_events() -> None:
    findings = rule_based_root_cause([
        {
            "type": "Normal",
            "reason": "SomethingUnrelated",
            "message": "nothing to see here",
            "count": 1,
            "first_timestamp": "2026-10-19T10:00:00Z",
            "last_timestamp": "2026-10-19T10:00:00Z",
            "involved_object": {"kind": "Pod", "name": "x"},
        }
    ])
    assert findings.root_cause == "no recent change event found"


class _StubLLMClient:
    def __init__(self, text: str) -> None:
        self._text = text
        self.received_tools: list[dict[str, object]] | None = None

    def complete(
        self, messages: list[Message], tools: list[dict[str, object]], system: str
    ) -> CompletionResult:
        self.received_tools = tools
        return CompletionResult(
            text=self._text,
            tool_calls=[],
            usage=Usage(input_tokens=20, output_tokens=10),
            stop_reason="end_turn",
        )


def test_llm_no_tools_root_cause_makes_zero_tool_calls() -> None:
    stub = _StubLLMClient("root cause: bad PORT env var on paymentservice")
    findings, usage = llm_no_tools_root_cause(
        "BoutiquePodCrashLooping", {"pod": "paymentservice-abc"}, {"summary": "crash looping"}, stub
    )
    assert stub.received_tools == []
    assert findings.root_cause == "root cause: bad PORT env var on paymentservice"
    assert usage.input_tokens == 20
