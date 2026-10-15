from boutique_manifest import real_containers
from chaos.scenarios.bad_deploy import BadDeployScenario
from fake_k8s import FakeK8sClient


def _seed_frontend(fake: FakeK8sClient) -> None:
    fake.seed_deployment("frontend", real_containers("frontend"))


def test_inject_sets_bad_tag_and_returns_prior_image() -> None:
    fake = FakeK8sClient()
    _seed_frontend(fake)
    scenario = BadDeployScenario()
    prior_image = real_containers("frontend")[0]["image"]

    snapshot = scenario.inject(fake, "frontend")

    assert snapshot == {"image": prior_image}
    patched = fake.deployments["frontend"]["containers"][0]
    assert patched["name"] == "server"
    assert patched["image"] == prior_image.rsplit(":", 1)[0] + ":does-not-exist"


def test_revert_restores_prior_image() -> None:
    fake = FakeK8sClient()
    _seed_frontend(fake)
    scenario = BadDeployScenario()
    snapshot = scenario.inject(fake, "frontend")

    scenario.revert(fake, "frontend", snapshot)

    reverted = fake.deployments["frontend"]["containers"][0]
    assert reverted == real_containers("frontend")[0]


def test_ground_truth_uses_passed_service() -> None:
    gt = BadDeployScenario().ground_truth("frontend")
    assert gt["affected_service"] == "frontend"
    assert "image tag" in gt["root_cause_label"]
