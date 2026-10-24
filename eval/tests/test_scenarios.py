from chaos.cli import _SCENARIOS
from eval.scenarios import (
    SCENARIO_ALERTS,
    SCENARIO_NAMES,
    build_synthetic_alert,
    incident_fields_from_alert,
)


def test_all_ten_scenarios_present() -> None:
    expected = {
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
    }
    assert set(SCENARIO_NAMES) == expected
    assert set(SCENARIO_ALERTS.keys()) == expected


def test_every_chaos_scenario_has_a_map_entry() -> None:
    assert set(SCENARIO_ALERTS.keys()) == set(_SCENARIOS.keys())


def test_scenario_names_matches_map_keys() -> None:
    assert set(SCENARIO_NAMES) == set(SCENARIO_ALERTS.keys())


def test_known_scenarios_map_to_expected_alertnames() -> None:
    assert SCENARIO_ALERTS["crash_loop"] == "BoutiquePodCrashLooping"
    assert SCENARIO_ALERTS["oom"] == "BoutiquePodOOMKilled"
    assert SCENARIO_ALERTS["bad_deploy"] == "BoutiquePodNotReady"
    assert SCENARIO_ALERTS["cpu_throttle"] == "BoutiqueCPUThrottlingHigh"
    assert SCENARIO_ALERTS["slow_redis"] is None


def test_build_synthetic_alert_for_slow_redis() -> None:
    alert = build_synthetic_alert("slow_redis", "redis-cart")
    assert alert["alertname"] == "ScenarioSyntheticAlert"
    assert alert["labels"]["scenario"] == "slow_redis"
    assert (
        "toxiproxy" in alert["annotations"]["description"].lower()
        or "latency" in alert["annotations"]["description"].lower()
    )


def test_incident_fields_from_alert_shape() -> None:
    fields = incident_fields_from_alert(
        "BoutiquePodCrashLooping",
        {"pod": "paymentservice-abc", "service": "paymentservice"},
        {"summary": "crash looping"},
    )
    assert fields["alertname"] == "BoutiquePodCrashLooping"
    assert fields["status"] == "received"
    assert fields["labels"]["service"] == "paymentservice"
    assert fields["fingerprint"].startswith("eval-BoutiquePodCrashLooping-")


def test_incident_fields_from_alert_fingerprints_differ_with_run_id() -> None:
    # Every eval run (whether a different scenario or just a different
    # repeat of the SAME scenario) must get its own fingerprint, since each
    # represents an independent, fresh incident - not a real-world alert
    # that should dedupe against incidents' unique-while-received index the
    # way a genuine repeated Alertmanager firing would.
    oom_alert = build_synthetic_alert("oom", "boutique")
    bad_deploy_alert = build_synthetic_alert("bad_deploy", "boutique")

    oom_fields = incident_fields_from_alert(
        oom_alert["alertname"], oom_alert["labels"], oom_alert["annotations"], run_id="oom-r0"
    )
    bad_deploy_fields = incident_fields_from_alert(
        bad_deploy_alert["alertname"],
        bad_deploy_alert["labels"],
        bad_deploy_alert["annotations"],
        run_id="bad_deploy-r0",
    )
    assert oom_fields["fingerprint"] != bad_deploy_fields["fingerprint"]

    oom_repeat0 = incident_fields_from_alert(
        oom_alert["alertname"], oom_alert["labels"], oom_alert["annotations"], run_id="oom-r0"
    )
    oom_repeat1 = incident_fields_from_alert(
        oom_alert["alertname"], oom_alert["labels"], oom_alert["annotations"], run_id="oom-r1"
    )
    assert oom_repeat0["fingerprint"] != oom_repeat1["fingerprint"]


def test_incident_fields_from_alert_defaults_run_id_to_empty() -> None:
    fields = incident_fields_from_alert(
        "BoutiquePodCrashLooping",
        {"pod": "paymentservice-abc", "service": "paymentservice"},
        {"summary": "crash looping"},
    )
    assert fields["fingerprint"] == "eval-BoutiquePodCrashLooping-paymentservice"
