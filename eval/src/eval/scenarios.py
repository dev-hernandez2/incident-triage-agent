"""Maps chaos scenarios to the Prometheus alert they should trigger, and
builds synthetic alerts for scenarios no alert rule covers."""

from typing import Any

SCENARIO_ALERTS: dict[str, str | None] = {
    "crash_loop": "BoutiquePodCrashLooping",
    "oom": "BoutiquePodOOMKilled",
    "bad_deploy": "BoutiquePodNotReady",
    "cpu_throttle": "BoutiqueCPUThrottlingHigh",
    "slow_redis": None,
}

SCENARIO_NAMES: tuple[str, ...] = (
    "crash_loop",
    "oom",
    "bad_deploy",
    "cpu_throttle",
    "slow_redis",
)


def build_synthetic_alert(scenario: str, service: str) -> dict[str, Any]:
    """Build a synthetic alert for scenarios without a corresponding alert rule.

    Args:
        scenario: The scenario name (e.g., 'slow_redis')
        service: The service name affected by the scenario

    Returns:
        A dict with alertname, labels, and annotations matching alert format.
    """
    from chaos.scenarios.base import load_definition

    definition = load_definition(scenario)
    return {
        "alertname": "ScenarioSyntheticAlert",
        "labels": {"scenario": scenario, "service": service},
        "annotations": {
            "summary": f"Synthetic alert for chaos scenario {scenario!r}",
            "description": definition.description,
        },
    }


def incident_fields_from_alert(
    alertname: str, labels: dict[str, str], annotations: dict[str, str]
) -> dict[str, Any]:
    """Extract fields needed to construct a db.models.Incident from an alert.

    Args:
        alertname: The alert name (e.g., 'BoutiquePodCrashLooping')
        labels: Alert labels dict
        annotations: Alert annotations dict

    Returns:
        A dict with keys: fingerprint, alertname, labels, annotations, status
    """
    fingerprint = f"eval-{alertname}-{labels.get('service', labels.get('pod', 'unknown'))}"
    return {
        "fingerprint": fingerprint,
        "alertname": alertname,
        "labels": labels,
        "annotations": annotations,
        "status": "received",
    }
