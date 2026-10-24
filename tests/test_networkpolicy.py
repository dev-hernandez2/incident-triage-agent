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
    assert 9092 in all_ports  # Kafka (agent's consumer input path)
    assert 5432 in all_ports  # Postgres (incidents/tool_calls/findings/audit_log)


def test_agent_networkpolicy_documents_llm_egress_limitation() -> None:
    raw = (_K8S_DIR / "networkpolicy-agent.yaml").read_text()
    assert "0.0.0.0/0" in raw
    assert "hostname" in raw.lower() or "FQDN" in raw


def test_executor_networkpolicy_selects_executor_pods_only() -> None:
    manifest = yaml.safe_load((_K8S_DIR / "networkpolicy-executor.yaml").read_text())
    assert manifest["spec"]["podSelector"]["matchLabels"]["app"] == "triage-executor"


def test_executor_networkpolicy_allows_kafka_postgres_and_discord_egress() -> None:
    manifest = yaml.safe_load((_K8S_DIR / "networkpolicy-executor.yaml").read_text())
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
    raw = (_K8S_DIR / "networkpolicy-executor.yaml").read_text()
    assert "Discord" in raw or "discord" in raw
