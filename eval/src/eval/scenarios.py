"""Maps chaos scenarios to the Prometheus alert they should trigger, and
builds synthetic alerts for scenarios no alert rule covers."""

from typing import Any

SCENARIO_ALERTS: dict[str, str | None] = {
    "crash_loop": "BoutiquePodCrashLooping",
    "oom": "BoutiquePodOOMKilled",
    "bad_deploy": "BoutiquePodNotReady",
    "cpu_throttle": "BoutiqueCPUThrottlingHigh",
    "slow_redis": None,
    "failing_readiness_probe": "BoutiqueReadinessProbeFailing",
    "dns_failure": "BoutiqueDnsResolutionFailing",
    "expired_tls_cert": None,
    "red_herring": None,
    "prompt_injection": None,
}

SCENARIO_NAMES: tuple[str, ...] = (
    "crash_loop",
    "oom",
    "bad_deploy",
    "cpu_throttle",
    "slow_redis",
    "failing_readiness_probe",
    "dns_failure",
    "expired_tls_cert",
    "red_herring",
    "prompt_injection",
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
    alertname: str, labels: dict[str, str], annotations: dict[str, str], run_id: str = ""
) -> dict[str, Any]:
    """Extract fields needed to construct a db.models.Incident from an alert.

    Args:
        alertname: The alert name (e.g., 'BoutiquePodCrashLooping')
        labels: Alert labels dict
        annotations: Alert annotations dict
        run_id: An extra token the caller mixes into the fingerprint to keep
            it unique across independent eval runs (e.g. "{scenario}-r{repeat}").
            A real Alertmanager fingerprint is deliberately stable so the same
            real-world alert firing twice dedupes against incidents' unique-
            while-received index; each eval run instead represents an
            independent, fresh incident, so this breaks that intentional
            stability on purpose for the eval harness's own synthetic incidents.

    Returns:
        A dict with keys: fingerprint, alertname, labels, annotations, status
    """
    service_part = labels.get("service", labels.get("pod", "unknown"))
    run_part = f"-{run_id}" if run_id else ""
    fingerprint = f"eval-{alertname}-{service_part}{run_part}"
    return {
        "fingerprint": fingerprint,
        "alertname": alertname,
        "labels": labels,
        "annotations": annotations,
        "status": "received",
    }
