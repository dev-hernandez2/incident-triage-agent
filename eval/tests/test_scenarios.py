from chaos.cli import _SCENARIOS
from eval.scenarios import (
    SCENARIO_ALERTS,
    SCENARIO_NAMES,
    build_synthetic_alert,
    incident_fields_from_alert,
)


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
