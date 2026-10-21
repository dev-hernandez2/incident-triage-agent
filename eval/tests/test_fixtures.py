import json
from pathlib import Path

import pytest
from agent.tools.base import ToolSpec
from pydantic import BaseModel

from eval.fixtures import FixtureExhaustedError, recording_tools, replaying_tools


class _EchoInput(BaseModel):
    value: str


def _make_echo_tool(name: str) -> ToolSpec:
    def handler(args: BaseModel) -> str:
        assert isinstance(args, _EchoInput)
        return f"echo:{args.value}"

    return ToolSpec(
        name=name,
        description="echoes input",
        input_model=_EchoInput,
        timeout_s=5.0,
        handler=handler,
    )


def test_recording_tools_writes_fixture_file(tmp_path: Path) -> None:
    fixture_path = tmp_path / "run-0.json"
    tools = recording_tools([_make_echo_tool("echo_a"), _make_echo_tool("echo_b")], fixture_path)

    by_name = {t.name: t for t in tools}
    result_a = by_name["echo_a"].handler(_EchoInput(value="first"))
    result_b = by_name["echo_b"].handler(_EchoInput(value="second"))

    assert result_a == "echo:first"
    assert result_b == "echo:second"

    recorded = json.loads(fixture_path.read_text())
    assert recorded == [
        {"index": 0, "tool": "echo_a", "args": {"value": "first"}, "output": "echo:first"},
        {"index": 1, "tool": "echo_b", "args": {"value": "second"}, "output": "echo:second"},
    ]


def test_replaying_tools_returns_recorded_output_in_order(tmp_path: Path) -> None:
    fixture_path = tmp_path / "run-0.json"
    fixture_path.write_text(json.dumps([
        {"index": 0, "tool": "echo_a", "args": {"value": "first"}, "output": "echo:first"},
        {"index": 1, "tool": "echo_b", "args": {"value": "second"}, "output": "echo:second"},
    ]))

    tools = replaying_tools([_make_echo_tool("echo_a"), _make_echo_tool("echo_b")], fixture_path)
    by_name = {t.name: t for t in tools}

    assert by_name["echo_a"].handler(_EchoInput(value="anything")) == "echo:first"
    assert by_name["echo_b"].handler(_EchoInput(value="anything")) == "echo:second"


def test_replaying_tools_raises_when_a_tool_has_no_recorded_entries(tmp_path: Path) -> None:
    fixture_path = tmp_path / "run-0.json"
    fixture_path.write_text(json.dumps([
        {"index": 0, "tool": "echo_a", "args": {"value": "first"}, "output": "echo:first"},
    ]))

    tools = replaying_tools([_make_echo_tool("echo_a"), _make_echo_tool("echo_b")], fixture_path)
    by_name = {t.name: t for t in tools}

    with pytest.raises(FixtureExhaustedError):
        by_name["echo_b"].handler(_EchoInput(value="anything"))


def test_replaying_tools_tolerates_interleaved_calls_to_different_tools(tmp_path: Path) -> None:
    fixture_path = tmp_path / "run-0.json"
    fixture_path.write_text(json.dumps([
        {"index": 0, "tool": "echo_a", "args": {"value": "a1"}, "output": "echo:a1"},
        {"index": 1, "tool": "echo_b", "args": {"value": "b1"}, "output": "echo:b1"},
        {"index": 2, "tool": "echo_a", "args": {"value": "a2"}, "output": "echo:a2"},
    ]))

    tools = replaying_tools([_make_echo_tool("echo_a"), _make_echo_tool("echo_b")], fixture_path)
    by_name = {t.name: t for t in tools}

    # Real model behavior: call the same tool twice in a row, rather than
    # matching the fixture's exact recorded global order. Each tool's own
    # per-name cursor still advances correctly.
    assert by_name["echo_a"].handler(_EchoInput(value="anything")) == "echo:a1"
    assert by_name["echo_a"].handler(_EchoInput(value="anything")) == "echo:a2"
    assert by_name["echo_b"].handler(_EchoInput(value="anything")) == "echo:b1"


def test_replaying_tools_raises_when_exhausted(tmp_path: Path) -> None:
    fixture_path = tmp_path / "run-0.json"
    fixture_path.write_text(json.dumps([
        {"index": 0, "tool": "echo_a", "args": {"value": "first"}, "output": "echo:first"},
    ]))

    tools = replaying_tools([_make_echo_tool("echo_a")], fixture_path)
    by_name = {t.name: t for t in tools}

    by_name["echo_a"].handler(_EchoInput(value="anything"))
    with pytest.raises(FixtureExhaustedError):
        by_name["echo_a"].handler(_EchoInput(value="anything"))
