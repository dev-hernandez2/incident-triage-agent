import time

import pytest
from agent.tools.base import ToolError, ToolSpec, run_tool, timed_run_tool
from pydantic import BaseModel, ValidationError


class EchoInput(BaseModel):
    message: str
    count: int


def _echo_handler(args: BaseModel) -> str:
    assert isinstance(args, EchoInput)
    return args.message * args.count


ECHO_SPEC = ToolSpec(
    name="echo",
    description="test tool",
    input_model=EchoInput,
    timeout_s=2.0,
    handler=_echo_handler,
)


def test_valid_args_run_successfully() -> None:
    result = run_tool(ECHO_SPEC, {"message": "hi", "count": 2})
    assert result.output == "hihi"
    assert result.truncated is False


def test_invalid_args_raise_validation_error() -> None:
    with pytest.raises(ValidationError):
        run_tool(ECHO_SPEC, {"message": "hi"})


def test_output_over_4kb_is_truncated_with_note() -> None:
    result = run_tool(ECHO_SPEC, {"message": "word more text here ", "count": 1_000})
    assert result.truncated is True
    assert "truncated" in result.output
    assert len(result.output.encode("utf-8")) < 10_000


def test_handler_exceeding_timeout_raises_tool_error() -> None:
    def slow_handler(args: BaseModel) -> str:
        time.sleep(1.0)
        return "done"

    spec = ToolSpec(
        name="slow",
        description="test tool",
        input_model=EchoInput,
        timeout_s=0.05,
        handler=slow_handler,
    )
    with pytest.raises(ToolError):
        run_tool(spec, {"message": "x", "count": 1})


def test_timed_run_tool_reports_error_and_duration() -> None:
    def failing_handler(args: BaseModel) -> str:
        raise ToolError("boom")

    spec = ToolSpec(
        name="failing",
        description="test tool",
        input_model=EchoInput,
        timeout_s=2.0,
        handler=failing_handler,
    )
    result, error, duration_ms = timed_run_tool(spec, {"message": "x", "count": 1})
    assert result is None
    assert error == "boom"
    assert duration_ms >= 0
