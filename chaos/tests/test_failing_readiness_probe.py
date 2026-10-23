from boutique_manifest import real_containers
from chaos.scenarios.failing_readiness_probe import FailingReadinessProbeScenario
from fake_k8s import FakeK8sClient


def test_inject_patches_readiness_probe_path_and_returns_prior_probe() -> None:
    fake = FakeK8sClient()
    fake.seed_deployment("frontend", real_containers("frontend"))
    scenario = FailingReadinessProbeScenario()

    snapshot = scenario.inject(fake, "frontend")

    prior_probe = real_containers("frontend")[0]["readinessProbe"]
    assert snapshot == {"readinessProbe": prior_probe}
    patched = fake.deployments["frontend"]["containers"][0]
    assert patched["readinessProbe"]["httpGet"]["path"] == "/this-path-does-not-exist"
    assert patched["readinessProbe"]["httpGet"]["port"] == prior_probe["httpGet"]["port"]


def test_revert_restores_prior_readiness_probe() -> None:
    fake = FakeK8sClient()
    fake.seed_deployment("frontend", real_containers("frontend"))
    scenario = FailingReadinessProbeScenario()
    snapshot = scenario.inject(fake, "frontend")

    scenario.revert(fake, "frontend", snapshot)

    reverted = fake.deployments["frontend"]["containers"][0]
    assert reverted == real_containers("frontend")[0]


def test_ground_truth_uses_passed_service() -> None:
    gt = FailingReadinessProbeScenario().ground_truth("frontend")
    assert gt["affected_service"] == "frontend"
    assert "readiness probe" in gt["root_cause_label"]
