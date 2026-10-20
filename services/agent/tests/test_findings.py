import pytest
from agent.findings import Evidence, Findings, findings_tool_schema
from pydantic import ValidationError


def test_valid_findings_construct_successfully() -> None:
    findings = Findings(
        summary="cartservice is crash-looping",
        root_cause="missing REDIS_ADDR env var",
        confidence="high",
        evidence=[Evidence(tool_call_id="abc-123", detail="pod shows CrashLoopBackOff")],
        affected_services=["cartservice"],
        suggested_fix="set REDIS_ADDR on the cartservice deployment",
        ruled_out=["network policy block"],
        status="complete",
    )
    assert findings.confidence == "high"
    assert findings.evidence[0].tool_call_id == "abc-123"


def test_confidence_rejects_values_outside_the_allowed_set() -> None:
    with pytest.raises(ValidationError):
        Findings(
            summary="x",
            root_cause="x",
            confidence="extremely high",  # type: ignore[arg-type]
            evidence=[],
            affected_services=[],
            suggested_fix="x",
            ruled_out=[],
            status="complete",
        )


def test_status_rejects_values_outside_the_allowed_set() -> None:
    with pytest.raises(ValidationError):
        Findings(
            summary="x",
            root_cause="x",
            confidence="low",
            evidence=[],
            affected_services=[],
            suggested_fix="x",
            ruled_out=[],
            status="in_progress",  # type: ignore[arg-type]
        )


def test_findings_tool_schema_excludes_status() -> None:
    schema = findings_tool_schema()
    assert schema["name"] == "submit_findings"
    input_schema = schema["input_schema"]
    assert isinstance(input_schema, dict)
    properties = input_schema["properties"]
    assert "status" not in properties
    assert "summary" in properties
    assert "evidence" in properties
