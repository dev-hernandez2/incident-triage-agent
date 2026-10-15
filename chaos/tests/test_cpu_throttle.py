from boutique_manifest import real_containers
from chaos.scenarios.cpu_throttle import CpuThrottleScenario
from fake_k8s import FakeK8sClient


def _seed_recommendationservice(fake: FakeK8sClient) -> None:
    fake.seed_deployment("recommendationservice", real_containers("recommendationservice"))


def test_inject_lowers_cpu_limit_and_returns_prior_resources() -> None:
    fake = FakeK8sClient()
    _seed_recommendationservice(fake)
    scenario = CpuThrottleScenario()

    snapshot = scenario.inject(fake, "recommendationservice")

    assert snapshot == {
        "resources": {
            "limits": {"cpu": "200m", "memory": "450Mi"},
            "requests": {"cpu": "100m", "memory": "220Mi"},
        }
    }
    patched = fake.deployments["recommendationservice"]["containers"][0]
    assert patched["name"] == "server"
    assert patched["resources"]["limits"]["cpu"] == "10m"
    assert patched["resources"]["limits"]["memory"] == "450Mi"


def test_revert_restores_prior_resources() -> None:
    fake = FakeK8sClient()
    _seed_recommendationservice(fake)
    scenario = CpuThrottleScenario()
    snapshot = scenario.inject(fake, "recommendationservice")

    scenario.revert(fake, "recommendationservice", snapshot)

    reverted = fake.deployments["recommendationservice"]["containers"][0]
    assert reverted == real_containers("recommendationservice")[0]


def test_ground_truth_uses_passed_service() -> None:
    gt = CpuThrottleScenario().ground_truth("recommendationservice")
    assert gt["affected_service"] == "recommendationservice"
    assert "throttling" in gt["root_cause_label"]
