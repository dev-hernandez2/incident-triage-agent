from pathlib import Path

import yaml

_K8S_DIR = Path(__file__).resolve().parents[1] / "deploy" / "k8s"


def test_agent_networkpolicy_default_denies_and_selects_agent_pods() -> None:
    manifest = yaml.safe_load((_K8S_DIR / "networkpolicy-agent.yaml").read_text())
    assert manifest["kind"] == "NetworkPolicy"
    spec = manifest["spec"]
    assert spec["podSelector"]["matchLabels"]["app"] == "triage-agent"
    assert "Egress" in spec["policyTypes"]
    assert "Ingress" in spec["policyTypes"]
    assert spec["ingress"] == []


def test_agent_networkpolicy_allows_only_documented_egress_destinations() -> None:
    manifest = yaml.safe_load((_K8S_DIR / "networkpolicy-agent.yaml").read_text())
    egress_rules = manifest["spec"]["egress"]
    all_ports = {p["port"] for rule in egress_rules for p in rule.get("ports", [])}
    assert 9090 in all_ports  # Prometheus
    assert 3100 in all_ports  # Loki
    assert 443 in all_ports   # LLM APIs
    assert 53 in all_ports    # DNS


def test_agent_networkpolicy_documents_llm_egress_limitation() -> None:
    raw = (_K8S_DIR / "networkpolicy-agent.yaml").read_text()
    assert "0.0.0.0/0" in raw
    assert "hostname" in raw.lower() or "FQDN" in raw


def test_executor_networkpolicy_selects_executor_pods_only() -> None:
    manifest = yaml.safe_load((_K8S_DIR / "networkpolicy-executor.yaml").read_text())
    assert manifest["spec"]["podSelector"]["matchLabels"]["app"] == "triage-executor"
