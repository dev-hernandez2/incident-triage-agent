"""Logs every tool invocation to the tool_calls table."""

import uuid
from typing import Any

from db.models import ToolCall
from sqlalchemy.orm import Session

from agent.tools.base import ToolResult


def record_tool_call(
    session: Session,
    incident_id: uuid.UUID,
    tool_name: str,
    args: dict[str, Any],
    result: ToolResult | None,
    error: str | None,
    duration_ms: int,
) -> ToolCall:
    row = ToolCall(
        incident_id=incident_id,
        tool=tool_name,
        args=args,
        duration_ms=duration_ms,
        output_bytes=len(result.output.encode("utf-8")) if result is not None else 0,
        truncated=result.truncated if result is not None else False,
        error=error,
    )
    session.add(row)
    session.flush()
    return row
