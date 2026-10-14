from chaos.scenarios.bad_deploy import BadDeployScenario
from fake_k8s import FakeK8sClient


def _seed_frontend(fake: FakeK8sClient) -> None:
    fake.seed_deployment(
        "frontend",
        [
            {
                "name": "frontend",
                "image": "repo/frontend:v0.10.7",
                "command": None,
                "env": [],
                "resources": {
                    "limits": {"cpu": "300m", "memory": "128Mi"},
                    "requests": {"cpu": "100m", "memory": "64Mi"},
                },
            }
        ],
    )


def test_inject_sets_bad_tag_and_returns_prior_image() -> None:
    fake = FakeK8sClient()
    _seed_frontend(fake)
    scenario = BadDeployScenario()

    snapshot = scenario.inject(fake, "frontend")

    assert snapshot == {"image": "repo/frontend:v0.10.7"}
    assert fake.deployments["frontend"]["containers"][0]["image"] == "repo/frontend:does-not-exist"


def test_revert_restores_prior_image() -> None:
    fake = FakeK8sClient()
    _seed_frontend(fake)
    scenario = BadDeployScenario()
    snapshot = scenario.inject(fake, "frontend")

    scenario.revert(fake, "frontend", snapshot)

    assert fake.deployments["frontend"]["containers"][0]["image"] == "repo/frontend:v0.10.7"


def test_ground_truth_uses_passed_service() -> None:
    gt = BadDeployScenario().ground_truth("frontend")
    assert gt["affected_service"] == "frontend"
    assert "image tag" in gt["root_cause_label"]
