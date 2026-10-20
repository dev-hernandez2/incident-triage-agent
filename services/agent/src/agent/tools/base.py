"""Shared tool-calling framework: schema export, timeout, truncation, redaction."""

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from agent.tools.redact import redact

MAX_OUTPUT_BYTES = 4096


class ToolError(Exception):
    """Raised by a tool implementation for an expected, reportable failure."""


@dataclass(frozen=True)
class ToolResult:
    output: str
    truncated: bool


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    timeout_s: float
    handler: Callable[[BaseModel], str]

    def json_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
        }


def _truncate(output: str) -> ToolResult:
    encoded = output.encode("utf-8")
    if len(encoded) <= MAX_OUTPUT_BYTES:
        return ToolResult(output=output, truncated=False)
    truncated_bytes = encoded[:MAX_OUTPUT_BYTES]
    truncated_text = truncated_bytes.decode("utf-8", errors="ignore")
    note = f"\n...[truncated, {len(encoded)} bytes total]"
    return ToolResult(output=truncated_text + note, truncated=True)


def run_tool(spec: ToolSpec, raw_args: dict[str, Any]) -> ToolResult:
    """Validates args, enforces timeout, then truncates and redacts the output."""
    args = spec.input_model.model_validate(raw_args)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(spec.handler, args)
        try:
            output = future.result(timeout=spec.timeout_s)
        except FutureTimeoutError as exc:
            raise ToolError(f"{spec.name} timed out after {spec.timeout_s}s") from exc

    return _truncate(redact(output))


def timed_run_tool(
    spec: ToolSpec, raw_args: dict[str, Any]
) -> tuple[ToolResult | None, str | None, int]:
    """Runs a tool, returning (result, error, duration_ms) for trace logging."""
    start = time.monotonic()
    try:
        result = run_tool(spec, raw_args)
        duration_ms = int((time.monotonic() - start) * 1000)
        return result, None, duration_ms
    except Exception as exc:  # noqa: BLE001 - surfaced to caller as a trace row
        duration_ms = int((time.monotonic() - start) * 1000)
        return None, str(exc), duration_ms
