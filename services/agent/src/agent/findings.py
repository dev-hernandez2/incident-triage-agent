"""Validated JSON findings output: the agent's conclusion for one incident."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    tool_call_id: str
    detail: str


class RollbackAction(BaseModel):
    type: Literal["rollback"]
    deployment: str
    reason: str


class RestartAction(BaseModel):
    type: Literal["restart"]
    deployment: str
    reason: str


class ScaleAction(BaseModel):
    type: Literal["scale"]
    deployment: str
    replicas: int
    reason: str


class ManualAction(BaseModel):
    type: Literal["manual"]
    reason: str


SuggestedFix = Annotated[
    RollbackAction | RestartAction | ScaleAction | ManualAction,
    Field(discriminator="type"),
]


class Findings(BaseModel):
    summary: str
    root_cause: str
    confidence: Literal["low", "medium", "high"]
    evidence: list[Evidence]
    affected_services: list[str]
    suggested_fix: SuggestedFix
    ruled_out: list[str]
    status: Literal["complete", "budget_exceeded"]


def findings_tool_schema() -> dict[str, object]:
    input_schema: dict[str, Any] = Findings.model_json_schema()
    del input_schema["properties"]["status"]
    input_schema["required"] = [f for f in input_schema["required"] if f != "status"]

    return {
        "name": "submit_findings",
        "description": (
            "Submit the final root-cause findings for this incident. Every evidence "
            "item's tool_call_id must match a tool call actually made during this "
            "investigation. suggested_fix must be exactly one of: rollback (revert a "
            "deployment to its previous version), restart (roll a deployment's pods), "
            "scale (change a deployment's replica count), or manual (free-text guidance "
            "when no safe automated action applies — this is never executed automatically)."
        ),
        "input_schema": input_schema,
    }
