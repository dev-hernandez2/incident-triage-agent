from obs.metrics import (
    COST_USD_TOTAL,
    INVESTIGATION_DURATION_SECONDS,
    INVESTIGATIONS_TOTAL,
    TOKENS_TOTAL,
    TOOL_ERRORS_TOTAL,
)
from prometheus_client import REGISTRY


def _sample_value(metric_name: str, labels: dict[str, str]) -> float | None:
    # prometheus_client strips a trailing "_total" from Counter family names
    # (e.g. "investigations_total" -> family "investigations"), but keeps it
    # on the individual sample name, so match on sample.name directly rather
    # than family.name.
    for family in REGISTRY.collect():
        for sample in family.samples:
            if sample.name == metric_name and sample.labels == labels:
                return sample.value
    return None


def test_investigations_total_increments_by_outcome() -> None:
    before = _sample_value("investigations_total", {"outcome": "complete"}) or 0.0
    INVESTIGATIONS_TOTAL.labels(outcome="complete").inc()
    after = _sample_value("investigations_total", {"outcome": "complete"})
    assert after == before + 1.0


def test_investigation_duration_seconds_observes() -> None:
    before = INVESTIGATION_DURATION_SECONDS._sum.get()
    INVESTIGATION_DURATION_SECONDS.observe(1.5)
    after = INVESTIGATION_DURATION_SECONDS._sum.get()
    assert after == before + 1.5


def test_tokens_total_increments_by_direction_and_model() -> None:
    before = (
        _sample_value("tokens_total", {"direction": "input", "model": "claude-haiku-5-5"}) or 0.0
    )
    TOKENS_TOTAL.labels(direction="input", model="claude-haiku-5-5").inc(42)
    after = _sample_value("tokens_total", {"direction": "input", "model": "claude-haiku-5-5"})
    assert after == before + 42


def test_cost_usd_total_increments_by_model() -> None:
    before = _sample_value("cost_usd_total", {"model": "claude-haiku-5-5"}) or 0.0
    COST_USD_TOTAL.labels(model="claude-haiku-5-5").inc(0.03)
    after = _sample_value("cost_usd_total", {"model": "claude-haiku-5-5"})
    assert after == before + 0.03


def test_tool_errors_total_increments_by_tool() -> None:
    before = _sample_value("tool_errors_total", {"tool": "list_pods"}) or 0.0
    TOOL_ERRORS_TOTAL.labels(tool="list_pods").inc()
    after = _sample_value("tool_errors_total", {"tool": "list_pods"})
    assert after == before + 1.0
