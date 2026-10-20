"""Scores a Findings object against a scenario's ground truth: exact
match first, LLM judge on a miss."""

import json
import re
from collections.abc import Callable
from pathlib import Path

from agent.findings import Findings
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
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise JudgeError(f"judge returned non-JSON output: {raw!r}") from exc

    try:
        return JudgeVerdict.model_validate(parsed)
    except ValidationError as exc:
        raise JudgeError(f"judge output failed validation: {exc}") from exc
