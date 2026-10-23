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
