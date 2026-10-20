"""search_logs tool: Loki LogQL query, newest 50 lines."""

import json

import httpx
from pydantic import BaseModel

from agent.tools.base import ToolError, ToolSpec

MAX_LINES = 50


class SearchLogsInput(BaseModel):
    service: str
    query: str
    since: str = "1h"


def make_search_logs(loki_url: str) -> ToolSpec:
    def handler(args: BaseModel) -> str:
        assert isinstance(args, SearchLogsInput)
        logql = (
            f'{{app="{args.service}"}} |~ "{args.query}"'
            if args.query
            else f'{{app="{args.service}"}}'
        )
        try:
            response = httpx.get(
                f"{loki_url}/loki/api/v1/query_range",
                params={
                    "query": logql,
                    "since": args.since,
                    "limit": MAX_LINES,
                    "direction": "backward",
                },
                timeout=10.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ToolError(f"loki query failed: {exc}") from exc

        payload = response.json()
        if payload.get("status") != "success":
            raise ToolError(f"loki query returned status={payload.get('status')!r}")

        lines = []
        for stream in payload["data"]["result"]:
            for ts, line in stream.get("values", []):
                lines.append({"timestamp": ts, "line": line, "labels": stream.get("stream", {})})
        lines.sort(key=lambda entry: entry["timestamp"], reverse=True)
        return json.dumps(lines[:MAX_LINES], default=str)

    return ToolSpec(
        name="search_logs",
        description="Search a service's logs via Loki LogQL, newest 50 lines.",
        input_model=SearchLogsInput,
        timeout_s=10.0,
        handler=handler,
    )
