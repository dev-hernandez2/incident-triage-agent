"""Two non-agentic baselines, scored through the same pipeline as the agent."""

from typing import Any, Protocol

from agent.findings import Findings, ManualAction
from llm.types import CompletionResult, Message, Usage, UserMessage

_CHANGE_REASONS = {"BackOff", "Pulled", "Scheduled", "Created", "Killing"}


def rule_based_root_cause(events: list[dict[str, Any]]) -> Findings:
    candidates = [e for e in events if e.get("reason") in _CHANGE_REASONS]
    if not candidates:
        root_cause = "no recent change event found"
    else:
        most_recent = max(candidates, key=lambda e: str(e.get("last_timestamp", "")))
        involved = most_recent.get("involved_object") or {}
        root_cause = f"most recent change: {most_recent.get('reason')} on {involved.get('name')}"

    return Findings(
        summary="rule-based baseline: most recent change event",
        root_cause=root_cause,
        confidence="low",
        evidence=[],
        affected_services=[],
        suggested_fix=ManualAction(type="manual", reason="manual investigation required"),
        ruled_out=[],
        status="complete",
    )


class LLMClientProtocol(Protocol):
    def complete(
        self, messages: list[Message], tools: list[dict[str, object]], system: str
    ) -> CompletionResult: ...


_NO_TOOLS_SYSTEM_PROMPT = (
    "You are triaging a Kubernetes alert for the Online Boutique demo "
    "application. You have no tools available. Based only on the alert's "
    "labels and annotations below, state your best guess at the root "
    "cause in one or two sentences."
)


def llm_no_tools_root_cause(
    alertname: str,
    labels: dict[str, str],
    annotations: dict[str, str],
    llm_client: LLMClientProtocol,
) -> tuple[Findings, Usage]:
    import json

    payload = {"alertname": alertname, "labels": labels, "annotations": annotations}
    message = UserMessage(text=f"<alert>\n{json.dumps(payload)}\n</alert>")

    result = llm_client.complete(messages=[message], tools=[], system=_NO_TOOLS_SYSTEM_PROMPT)
    root_cause = result.text or "no response from model"

    findings = Findings(
        summary="LLM-no-tools baseline: single completion, alert payload only",
        root_cause=root_cause,
        confidence="low",
        evidence=[],
        affected_services=[],
        suggested_fix=ManualAction(type="manual", reason="manual investigation required"),
        ruled_out=[],
        status="complete",
    )
    return findings, result.usage
