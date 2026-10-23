"""Prometheus collectors for the agent's investigation loop, plus a
helper to start the /metrics HTTP exposition server."""

from prometheus_client import Counter, Histogram, start_http_server

INVESTIGATIONS_TOTAL = Counter(
    "investigations_total", "Investigations completed, by outcome", ["outcome"]
)

INVESTIGATION_DURATION_SECONDS = Histogram(
    "investigation_duration_seconds", "Wall-clock duration of one investigation"
)

TOKENS_TOTAL = Counter(
    "tokens_total", "LLM tokens consumed, by direction and model", ["direction", "model"]
)

COST_USD_TOTAL = Counter("cost_usd_total", "LLM spend in USD, by model", ["model"])

TOOL_ERRORS_TOTAL = Counter(
    "tool_errors_total", "Tool calls that returned an error, by tool name", ["tool"]
)


def start_metrics_server(port: int) -> None:
    start_http_server(port)
