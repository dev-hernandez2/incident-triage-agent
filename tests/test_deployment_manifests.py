"""Tests for Kubernetes Secret and Deployment manifests."""

from pathlib import Path

import yaml

_K8S_DIR = Path(__file__).resolve().parents[1] / "deploy" / "k8s"


def test_secrets_example_has_no_real_looking_values() -> None:
    manifest = yaml.safe_load((_K8S_DIR / "secrets-example.yaml").read_text())
    assert manifest["kind"] == "Secret"
    for value in manifest["stringData"].values():
        assert value in ("CHANGE_ME", "") or value.startswith("CHANGE_ME")


def test_agent_deployment_uses_triage_agent_service_account_and_secret() -> None:
    manifest = yaml.safe_load((_K8S_DIR / "deployment-agent.yaml").read_text())
    assert manifest["kind"] == "Deployment"
    pod_spec = manifest["spec"]["template"]["spec"]
    assert pod_spec["serviceAccountName"] == "triage-agent"
    container = pod_spec["containers"][0]
    assert container["envFrom"][0]["secretRef"]["name"] == "triage-secrets"
    assert manifest["spec"]["template"]["metadata"]["labels"]["app"] == "triage-agent"


def test_executor_deployment_uses_triage_executor_service_account_and_secret() -> None:
    manifest = yaml.safe_load((_K8S_DIR / "deployment-executor.yaml").read_text())
    assert manifest["kind"] == "Deployment"
    pod_spec = manifest["spec"]["template"]["spec"]
    assert pod_spec["serviceAccountName"] == "triage-executor"
    container = pod_spec["containers"][0]
    assert container["envFrom"][0]["secretRef"]["name"] == "triage-secrets"


def test_agent_service_exists_and_selects_agent_pods_on_the_metrics_port() -> None:
    """The agent's ServiceMonitor (grafana-dashboard-agent.yaml) selects a
    Service, not the Deployment/pods directly -- Prometheus Operator
    discovers Services' Endpoints. This Service must exist, select the
    Deployment's pods, and expose a port named "metrics" matching the
    container's containerPort (9100) that the ServiceMonitor's
    endpoints[0].port references."""
    service = yaml.safe_load((_K8S_DIR / "service-agent.yaml").read_text())
    deployment = yaml.safe_load((_K8S_DIR / "deployment-agent.yaml").read_text())

    assert service["kind"] == "Service"
    assert service["metadata"]["namespace"] == "triage"
    assert service["spec"]["selector"] == deployment["spec"]["template"]["metadata"]["labels"]

    ports = {p["name"]: p for p in service["spec"]["ports"]}
    assert "metrics" in ports
    assert ports["metrics"]["port"] == 9100

    container = deployment["spec"]["template"]["spec"]["containers"][0]
    container_port = next(p for p in container["ports"] if p["name"] == "metrics")
    assert ports["metrics"]["targetPort"] == container_port["containerPort"]


def test_agent_service_matches_servicemonitor_selector_and_port() -> None:
    service = yaml.safe_load((_K8S_DIR / "service-agent.yaml").read_text())
    docs = list(yaml.safe_load_all((_K8S_DIR / "grafana-dashboard-agent.yaml").read_text()))
    service_monitor = next(doc for doc in docs if doc and doc["kind"] == "ServiceMonitor")

    assert service["metadata"]["labels"] == service_monitor["spec"]["selector"]["matchLabels"]
    assert service["metadata"]["namespace"] in service_monitor["spec"]["namespaceSelector"][
        "matchNames"
    ]
    monitored_port_name = service_monitor["spec"]["endpoints"][0]["port"]
    assert any(p["name"] == monitored_port_name for p in service["spec"]["ports"])
