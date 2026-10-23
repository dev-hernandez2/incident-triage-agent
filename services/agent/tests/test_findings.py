import pytest
from agent.findings import (
    Evidence,
    Findings,
    ManualAction,
    RestartAction,
    RollbackAction,
    ScaleAction,
    findings_tool_schema,
)
from pydantic import ValidationError


def _base_kwargs(**overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = dict(
        summary="cartservice is crash-looping",
        root_cause="missing REDIS_ADDR env var",
        confidence="high",
        evidence=[Evidence(tool_call_id="abc-123", detail="pod shows CrashLoopBackOff")],
        affected_services=["cartservice"],
        suggested_fix=RollbackAction(
            type="rollback", deployment="cartservice", reason="bad deploy"
        ),
        ruled_out=["network policy block"],
        status="complete",
    )
    defaults.update(overrides)
    return defaults


def test_valid_findings_construct_successfully_with_rollback_action() -> None:
    findings = Findings(**_base_kwargs())  # type: ignore[arg-type]
    assert findings.confidence == "high"
    assert isinstance(findings.suggested_fix, RollbackAction)
    assert findings.suggested_fix.deployment == "cartservice"


def test_restart_action_requires_deployment_and_reason() -> None:
    findings = Findings(
        **_base_kwargs(  # type: ignore[arg-type]
            suggested_fix=RestartAction(
                type="restart", deployment="cartservice", reason="stuck connection pool"
            )
        )
    )
    assert isinstance(findings.suggested_fix, RestartAction)


def test_scale_action_requires_replicas() -> None:
    findings = Findings(
        **_base_kwargs(  # type: ignore[arg-type]
            suggested_fix=ScaleAction(
                type="scale", deployment="checkoutservice", replicas=3, reason="under load"
            )
        )
    )
    assert isinstance(findings.suggested_fix, ScaleAction)
    assert findings.suggested_fix.replicas == 3


def test_manual_action_carries_only_reason() -> None:
    findings = Findings(
        **_base_kwargs(suggested_fix=ManualAction(type="manual", reason="needs human review"))  # type: ignore[arg-type]
    )
    assert isinstance(findings.suggested_fix, ManualAction)


def test_suggested_fix_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        Findings(**_base_kwargs(suggested_fix={"type": "delete_everything", "reason": "x"}))  # type: ignore[arg-type]


def test_suggested_fix_rejects_dict_missing_discriminator() -> None:
    with pytest.raises(ValidationError):
        Findings(**_base_kwargs(suggested_fix={"deployment": "cartservice", "reason": "x"}))  # type: ignore[arg-type]


def test_confidence_rejects_values_outside_the_allowed_set() -> None:
    with pytest.raises(ValidationError):
        Findings(
            **_base_kwargs(confidence="extremely high")  # type: ignore[arg-type]
        )


def test_status_rejects_values_outside_the_allowed_set() -> None:
    with pytest.raises(ValidationError):
        Findings(
            **_base_kwargs(status="in_progress")  # type: ignore[arg-type]
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
