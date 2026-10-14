from chaos.scenarios.oom import OomScenario
from tests.fake_k8s import FakeK8sClient


def _seed_cartservice(fake: FakeK8sClient) -> None:
    fake.seed_deployment(
        "cartservice",
        [
            {
                "name": "cartservice",
                "image": "repo/cartservice:v0.10.7",
                "command": None,
                "env": [],
                "resources": {"limits": {"cpu": "300m", "memory": "128Mi"}, "requests": {"cpu": "200m", "memory": "64Mi"}},
            }
        ],
    )


def test_inject_lowers_memory_limit_and_returns_prior_resources():
    fake = FakeK8sClient()
    _seed_cartservice(fake)
    scenario = OomScenario()

    snapshot = scenario.inject(fake, "cartservice")

    assert snapshot == {
        "resources": {"limits": {"cpu": "300m", "memory": "128Mi"}, "requests": {"cpu": "200m", "memory": "64Mi"}}
    }
    patched = fake.deployments["cartservice"]["containers"][0]["resources"]
    assert patched["limits"]["memory"] == "20Mi"
    assert patched["limits"]["cpu"] == "300m"


def test_revert_restores_prior_resources():
    fake = FakeK8sClient()
    _seed_cartservice(fake)
    scenario = OomScenario()
    snapshot = scenario.inject(fake, "cartservice")

    scenario.revert(fake, "cartservice", snapshot)

    assert fake.deployments["cartservice"]["containers"][0]["resources"] == {
        "limits": {"cpu": "300m", "memory": "128Mi"},
        "requests": {"cpu": "200m", "memory": "64Mi"},
    }


def test_ground_truth_uses_passed_service():
    gt = OomScenario().ground_truth("cartservice")
    assert gt["affected_service"] == "cartservice"
    assert "OOMKilled" in gt["root_cause_label"]
