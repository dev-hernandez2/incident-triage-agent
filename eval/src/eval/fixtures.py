"""Wraps ToolSpec handlers to record tool-call I/O for replay, or replay
previously recorded I/O without hitting a live cluster."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from agent.tools.base import ToolSpec
from pydantic import BaseModel


class FixtureExhaustedError(Exception):
    pass


def recording_tools(tools: list[ToolSpec], fixture_path: Path) -> list[ToolSpec]:
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    recorded: list[dict[str, Any]] = []

    def _wrap(spec: ToolSpec) -> ToolSpec:
        def handler(args: BaseModel) -> str:
            output = spec.handler(args)
            recorded.append(
                {
                    "index": len(recorded),
                    "tool": spec.name,
                    "args": args.model_dump(mode="json"),
                    "output": output,
                }
            )
            fixture_path.write_text(json.dumps(recorded, indent=2))
            return output

        return replace(spec, handler=handler)

    return [_wrap(spec) for spec in tools]


def replaying_tools(tools: list[ToolSpec], fixture_path: Path) -> list[ToolSpec]:
    """Replays each tool's recorded outputs in the order THAT TOOL was
    originally called, independent of what other tools were called in
    between. A real cluster answers "list pods" the same way regardless
    of what else was queried first, so a per-tool-name cursor tolerates
    a live model's investigation order diverging from the recorded
    transcript's exact global sequence - it only raises
    FixtureExhaustedError when a tool is called more times than it has
    recorded entries for, not whenever the overall call sequence shifts."""
    entries: list[dict[str, Any]] = json.loads(fixture_path.read_text())
    by_tool: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        by_tool.setdefault(entry["tool"], []).append(entry)
    cursors: dict[str, int] = {}

    def _wrap(spec: ToolSpec) -> ToolSpec:
        def handler(args: BaseModel) -> str:
            tool_entries = by_tool.get(spec.name, [])
            next_index = cursors.get(spec.name, 0)
            if next_index >= len(tool_entries):
                raise FixtureExhaustedError(
                    f"fixture {fixture_path} has no more recorded {spec.name!r} calls "
                    f"({len(tool_entries)} recorded), but {spec.name!r} was called again"
                )
            cursors[spec.name] = next_index + 1
            output = tool_entries[next_index]["output"]
            assert isinstance(output, str)
            return output

        return replace(spec, handler=handler)

    return [_wrap(spec) for spec in tools]
