import json
from pathlib import Path

_DASHBOARD_PATH = (
    Path(__file__).resolve().parents[1]
    / "deploy"
    / "monitoring"
    / "grafana-agent-dashboard.json"
)


def test_dashboard_json_is_well_formed() -> None:
    dashboard = json.loads(_DASHBOARD_PATH.read_text())
    assert "panels" in dashboard
    assert "title" in dashboard
    assert len(dashboard["panels"]) >= 4


def test_dashboard_references_all_five_agent_metrics() -> None:
    raw = _DASHBOARD_PATH.read_text()
    for metric in (
        "investigations_total",
        "investigation_duration_seconds",
        "tokens_total",
        "cost_usd_total",
        "tool_errors_total",
    ):
        assert metric in raw
