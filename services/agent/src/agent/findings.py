"""Validated JSON findings output: the agent's conclusion for one incident."""

from typing import Literal

from pydantic import BaseModel, create_model


class Evidence(BaseModel):
    tool_call_id: str
    detail: str


class Findings(BaseModel):
    summary: str
    root_cause: str
    confidence: Literal["low", "medium", "high"]
    evidence: list[Evidence]
    affected_services: list[str]
    suggested_fix: str
    ruled_out: list[str]
    status: Literal["complete", "budget_exceeded"]


_SubmitFindingsArgs = create_model(
    "SubmitFindingsArgs",
    __base__=BaseModel,
    summary=(str, ...),
    root_cause=(str, ...),
    confidence=(Literal["low", "medium", "high"], ...),
    evidence=(list[Evidence], ...),
    affected_services=(list[str], ...),
    suggested_fix=(str, ...),
    ruled_out=(list[str], ...),
)


def findings_tool_schema() -> dict[str, object]:
    return {
        "name": "submit_findings",
        "description": (
            "Submit the final root-cause findings for this incident. Every evidence "
            "item's tool_call_id must match a tool call actually made during this "
            "investigation."
        ),
        "input_schema": _SubmitFindingsArgs.model_json_schema(),
    }
