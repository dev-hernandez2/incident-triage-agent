"""Validated JSON findings output: the agent's conclusion for one incident."""

from typing import Any, Literal

from pydantic import BaseModel


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


def findings_tool_schema() -> dict[str, object]:
    input_schema: dict[str, Any] = Findings.model_json_schema()
    del input_schema["properties"]["status"]
    input_schema["required"] = [f for f in input_schema["required"] if f != "status"]

    return {
        "name": "submit_findings",
        "description": (
            "Submit the final root-cause findings for this incident. Every evidence "
            "item's tool_call_id must match a tool call actually made during this "
            "investigation."
        ),
        "input_schema": input_schema,
    }
