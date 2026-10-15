from boutique_manifest import real_containers
from chaos.scenarios.oom import OomScenario
from fake_k8s import FakeK8sClient


def _seed_cartservice(fake: FakeK8sClient) -> None:
    fake.seed_deployment("cartservice", real_containers("cartservice"))


def test_inject_lowers_memory_limit_and_returns_prior_resources() -> None:
    fake = FakeK8sClient()
    _seed_cartservice(fake)
    scenario = OomScenario()

    snapshot = scenario.inject(fake, "cartservice")

    assert snapshot == {
        "resources": {
            "limits": {"cpu": "300m", "memory": "128Mi"},
            "requests": {"cpu": "200m", "memory": "64Mi"},
        }
    }
    patched = fake.deployments["cartservice"]["containers"][0]
    assert patched["name"] == "server"
    assert patched["resources"]["limits"]["memory"] == "20Mi"
    assert patched["resources"]["limits"]["cpu"] == "300m"


def test_revert_restores_prior_resources() -> None:
    fake = FakeK8sClient()
    _seed_cartservice(fake)
    scenario = OomScenario()
    snapshot = scenario.inject(fake, "cartservice")

    scenario.revert(fake, "cartservice", snapshot)

    reverted = fake.deployments["cartservice"]["containers"][0]
    assert reverted == real_containers("cartservice")[0]


def test_ground_truth_uses_passed_service() -> None:
    gt = OomScenario().ground_truth("cartservice")
    assert gt["affected_service"] == "cartservice"
    assert "OOMKilled" in gt["root_cause_label"]
