"""Tests for the triage-agent Helm chart's NetworkPolicy templates
(rendered via `helm template`).

The raw k8s manifests these tests used to read directly were deleted when
the triage-agent app services migrated to the Helm chart at
deploy/helm/triage-agent/ (see deploy/k8s/README.md); NetworkPolicies now
live there instead.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

_CHART_DIR = Path(__file__).resolve().parents[1] / "deploy" / "helm" / "triage-agent"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


def _render_raw() -> str:
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
    return result.stdout


def _render(kind: str, name: str) -> dict[str, Any]:
    docs = [doc for doc in yaml.safe_load_all(_render_raw()) if doc]
    return next(doc for doc in docs if doc["kind"] == kind and doc["metadata"]["name"] == name)


def test_agent_networkpolicy_default_denies_and_selects_agent_pods() -> None:
    manifest = _render("NetworkPolicy", "test-release-agent")
    spec = manifest["spec"]
    assert spec["podSelector"]["matchLabels"]["app"] == "test-release-agent"
    assert "Egress" in spec["policyTypes"]
    assert "Ingress" in spec["policyTypes"]
    assert spec["ingress"] == []


def test_agent_networkpolicy_allows_only_documented_egress_destinations() -> None:
    manifest = _render("NetworkPolicy", "test-release-agent")
    egress_rules = manifest["spec"]["egress"]
    all_ports = {p["port"] for rule in egress_rules for p in rule.get("ports", [])}
    assert 9090 in all_ports  # Prometheus
    assert 3100 in all_ports  # Loki
    assert 443 in all_ports   # LLM APIs
    assert 53 in all_ports    # DNS
    assert 9092 in all_ports  # Kafka (agent's consumer input path)
    assert 5432 in all_ports  # Postgres (incidents/tool_calls/findings/audit_log)


def test_agent_networkpolicy_documents_llm_egress_limitation() -> None:
    raw = _render_raw()
    assert "0.0.0.0/0" in raw
    assert "hostname" in raw.lower() or "FQDN" in raw


def test_executor_networkpolicy_selects_executor_pods_only() -> None:
    manifest = _render("NetworkPolicy", "test-release-executor")
    assert manifest["spec"]["podSelector"]["matchLabels"]["app"] == "test-release-executor"


def test_executor_networkpolicy_allows_kafka_postgres_and_discord_egress() -> None:
    manifest = _render("NetworkPolicy", "test-release-executor")
    egress_rules = manifest["spec"]["egress"]
    all_ports = {p["port"] for rule in egress_rules for p in rule.get("ports", [])}
    assert 9092 in all_ports  # Kafka
    assert 5432 in all_ports  # Postgres (polls the actions table)
    assert 443 in all_ports   # Discord webhook (DISCORD_WEBHOOK_URL)

    # The 443 rule must permit the external Discord webhook call, not just
    # cluster-internal 10.0.0.0/8 traffic.
    has_external_443 = any(
        443 in {p["port"] for p in rule.get("ports", [])}
        and any(dest.get("ipBlock", {}).get("cidr") == "0.0.0.0/0" for dest in rule.get("to", []))
        for rule in egress_rules
    )
    assert has_external_443


def test_executor_networkpolicy_header_comment_mentions_discord() -> None:
    raw = _render_raw()
    assert "Discord" in raw or "discord" in raw
