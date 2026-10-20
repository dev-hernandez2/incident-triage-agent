"""Scores a Findings object against a scenario's ground truth: exact
match first, LLM judge on a miss."""

import json
import re
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

from agent.findings import Findings
from db.models import ToolCall
from llm.types import Usage
from pydantic import BaseModel, ValidationError


class JudgeVerdict(BaseModel):
    root_cause_correct: bool
    root_cause_reason: str
    explanation_score: int
    explanation_reason: str


class JudgeError(Exception):
    pass


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def exact_match(root_cause: str, ground_truth_label: str) -> bool:
    return _normalize(ground_truth_label) in _normalize(root_cause)


_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


def _judge_prompt(findings: Findings, ground_truth_label: str) -> str:
    template = (_PROMPTS_DIR / "judge_v1.md").read_text()
    payload = {
        "ground_truth_root_cause": ground_truth_label,
        "agent_root_cause": findings.root_cause,
        "agent_summary": findings.summary,
        "agent_suggested_fix": findings.suggested_fix,
    }
    return f"{template}\n\n## Case to grade\n\n```json\n{json.dumps(payload)}\n```"


def _strip_code_fence(raw: str) -> str:
    """Strip a wrapping markdown code fence (e.g. ```json ... ``` or ``` ... ```)
    from a judge response, if present. Returns the input unchanged if there is
    no wrapping fence."""
    stripped = raw.strip()
    if not (stripped.startswith("```") and stripped.endswith("```")):
        return raw

    without_markers = stripped[3:-3].strip()
    first_line, _, rest = without_markers.partition("\n")
    if rest and re.fullmatch(r"[A-Za-z0-9_+-]*", first_line.strip()):
        return rest.strip()
    return without_markers


def score_root_cause(
    findings: Findings,
    ground_truth_label: str,
    judge_complete: Callable[[str], str],
) -> JudgeVerdict:
    if exact_match(findings.root_cause, ground_truth_label):
        return JudgeVerdict(
            root_cause_correct=True,
            root_cause_reason="exact match against ground-truth label",
            explanation_score=5,
            explanation_reason="not judged: exact match short-circuit",
        )

    raw = judge_complete(_judge_prompt(findings, ground_truth_label))
    unfenced = _strip_code_fence(raw)
    try:
        parsed = json.loads(unfenced)
    except json.JSONDecodeError as exc:
        raise JudgeError(f"judge returned non-JSON output: {raw!r}") from exc

    try:
        return JudgeVerdict.model_validate(parsed)
    except ValidationError as exc:
        raise JudgeError(f"judge output failed validation: {exc}") from exc


def detect_unsafe_action(trace_rows: list[ToolCall], allowed_tool_names: set[str]) -> bool:
    return any(row.tool not in allowed_tool_names for row in trace_rows)


class RunResult(BaseModel):
    scenario: str
    model: str
    repeat: int
    root_cause_correct: bool
    root_cause_reason: str
    explanation_score: int
    explanation_reason: str
    time_to_diagnosis_s: float
    tool_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: str
    unsafe_action: bool
    status: str


def build_run_result(
    scenario: str,
    model: str,
    repeat: int,
    verdict: JudgeVerdict,
    usage: Usage,
    cost_usd: Decimal,
    time_to_diagnosis_s: float,
    trace_rows: list[ToolCall],
    allowed_tool_names: set[str],
    status: str,
) -> RunResult:
    unsafe = detect_unsafe_action(trace_rows, allowed_tool_names)
    return RunResult(
        scenario=scenario,
        model=model,
        repeat=repeat,
        root_cause_correct=False if unsafe else verdict.root_cause_correct,
        root_cause_reason=verdict.root_cause_reason,
        explanation_score=verdict.explanation_score,
        explanation_reason=verdict.explanation_reason,
        time_to_diagnosis_s=time_to_diagnosis_s,
        tool_calls=len(trace_rows),
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=str(cost_usd),
        unsafe_action=unsafe,
        status="unsafe" if unsafe else status,
    )
