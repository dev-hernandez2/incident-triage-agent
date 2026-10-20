"""query_metrics tool: Prometheus range query, summarized per series."""

import json
from typing import Any

import httpx
from pydantic import BaseModel

from agent.tools.base import ToolError, ToolSpec

MAX_SERIES = 10


class QueryMetricsInput(BaseModel):
    promql: str
    start: str
    end: str
    step: str = "60s"


def make_query_metrics(prometheus_url: str) -> ToolSpec:
    def handler(args: BaseModel) -> str:
        assert isinstance(args, QueryMetricsInput)
        try:
            response = httpx.get(
                f"{prometheus_url}/api/v1/query_range",
                params={
                    "query": args.promql,
                    "start": args.start,
                    "end": args.end,
                    "step": args.step,
                },
                timeout=10.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ToolError(f"prometheus query failed: {exc}") from exc

        payload = response.json()
        if payload.get("status") != "success":
            raise ToolError(f"prometheus query returned status={payload.get('status')!r}")

        series = payload["data"]["result"][:MAX_SERIES]
        return json.dumps([_summarize_series(s) for s in series], default=str)

    return ToolSpec(
        name="query_metrics",
        description="Run a Prometheus range query and summarize min/max/last per series "
        "(max 10 series).",
        input_model=QueryMetricsInput,
        timeout_s=10.0,
        handler=handler,
    )


def _summarize_series(series: dict[str, Any]) -> dict[str, Any]:
    values = [float(v) for _, v in series.get("values", [])]
    if not values:
        return {"metric": series.get("metric", {}), "min": None, "max": None, "last": None}
    return {
        "metric": series.get("metric", {}),
        "min": min(values),
        "max": max(values),
        "last": values[-1],
    }
