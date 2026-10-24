"""Tests for the triage-agent Helm chart's Secret, Deployment, and Service
templates (rendered via `helm template`).

The raw k8s manifests these tests used to read directly were deleted when
the triage-agent app services migrated to the Helm chart at
deploy/helm/triage-agent/ (see deploy/k8s/README.md); RBAC/Deployments/
Services/NetworkPolicies now live there instead.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

_CHART_DIR = Path(__file__).resolve().parents[1] / "deploy" / "helm" / "triage-agent"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


def _render() -> list[dict[str, Any]]:
    result = subprocess.run(
        [
            "helm",
            "template",
            "test-release",
            str(_CHART_DIR),
            "--set",
            "secrets.CHANGE_ME=CHANGE_ME",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _find(docs: list[dict[str, Any]], kind: str, name: str) -> dict[str, Any]:
    return next(doc for doc in docs if doc["kind"] == kind and doc["metadata"]["name"] == name)


def test_secret_template_only_renders_placeholder_values() -> None:
    docs = _render()
    secret = _find(docs, "Secret", "test-release-secrets")
    assert secret["kind"] == "Secret"
    for value in secret["stringData"].values():
        assert value in ("CHANGE_ME", "") or value.startswith("CHANGE_ME")


def test_agent_deployment_uses_triage_agent_service_account_and_secret() -> None:
    docs = _render()
    deployment = _find(docs, "Deployment", "test-release-agent")
    pod_spec = deployment["spec"]["template"]["spec"]
    assert pod_spec["serviceAccountName"] == "test-release-agent"
    container = pod_spec["containers"][0]
    assert container["envFrom"][0]["secretRef"]["name"] == "test-release-secrets"
    assert deployment["spec"]["template"]["metadata"]["labels"]["app"] == "test-release-agent"


def test_executor_deployment_uses_triage_executor_service_account_and_secret() -> None:
    docs = _render()
    deployment = _find(docs, "Deployment", "test-release-executor")
    pod_spec = deployment["spec"]["template"]["spec"]
    assert pod_spec["serviceAccountName"] == "test-release-executor"
    container = pod_spec["containers"][0]
    assert container["envFrom"][0]["secretRef"]["name"] == "test-release-secrets"


def test_agent_service_exists_and_selects_agent_pods_on_the_metrics_port() -> None:
    """The agent's ServiceMonitor selects a Service, not the Deployment/pods
    directly -- Prometheus Operator discovers Services' Endpoints. This
    Service must exist, select the Deployment's pods, and expose a port
    named "metrics" matching the container's containerPort (9100) that the
    ServiceMonitor's endpoints[0].port references."""
    docs = _render()
    service = _find(docs, "Service", "test-release-agent")
    deployment = _find(docs, "Deployment", "test-release-agent")

    assert service["metadata"]["namespace"] == "triage"
    assert service["spec"]["selector"] == deployment["spec"]["template"]["metadata"]["labels"]

    ports = {p["name"]: p for p in service["spec"]["ports"]}
    assert "metrics" in ports
    assert ports["metrics"]["port"] == 9100

    container = deployment["spec"]["template"]["spec"]["containers"][0]
    container_port = next(p for p in container["ports"] if p["name"] == "metrics")
    assert ports["metrics"]["targetPort"] == container_port["containerPort"]


def test_agent_service_matches_servicemonitor_selector_and_port() -> None:
    docs = _render()
    service = _find(docs, "Service", "test-release-agent")
    service_monitor = _find(docs, "ServiceMonitor", "test-release-agent")

    assert service["metadata"]["labels"] == service_monitor["spec"]["selector"]["matchLabels"]
    assert service["metadata"]["namespace"] in service_monitor["spec"]["namespaceSelector"][
        "matchNames"
    ]
    monitored_port_name = service_monitor["spec"]["endpoints"][0]["port"]
    assert any(p["name"] == monitored_port_name for p in service["spec"]["ports"])
