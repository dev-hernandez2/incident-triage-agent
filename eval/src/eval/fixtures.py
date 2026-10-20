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


class FixtureMismatchError(Exception):
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
    entries: list[dict[str, Any]] = json.loads(fixture_path.read_text())
    cursor = {"next": 0}

    def _wrap(spec: ToolSpec) -> ToolSpec:
        def handler(args: BaseModel) -> str:
            if cursor["next"] >= len(entries):
                raise FixtureExhaustedError(
                    f"fixture {fixture_path} exhausted after {len(entries)} recorded calls, "
                    f"but tool {spec.name!r} was called again"
                )
            entry = entries[cursor["next"]]
            if entry["tool"] != spec.name:
                raise FixtureMismatchError(
                    f"fixture {fixture_path} expected call #{cursor['next']} to be "
                    f"{entry['tool']!r}, but {spec.name!r} was called"
                )
            cursor["next"] += 1
            output = entry["output"]
            assert isinstance(output, str)
            return output

        return replace(spec, handler=handler)

    return [_wrap(spec) for spec in tools]
