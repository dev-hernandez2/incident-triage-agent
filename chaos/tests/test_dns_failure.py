from boutique_manifest import real_containers
from chaos.scenarios.dns_failure import DnsFailureScenario
from fake_k8s import FakeK8sClient


def _seed_frontend(fake: FakeK8sClient) -> None:
    fake.seed_deployment("frontend", real_containers("frontend"))


def test_inject_patches_dependency_env_var_and_returns_prior_env() -> None:
    fake = FakeK8sClient()
    _seed_frontend(fake)
    scenario = DnsFailureScenario()

    snapshot = scenario.inject(fake, "frontend")

    prior_env = real_containers("frontend")[0]["env"]
    assert snapshot == {"env": prior_env}
    patched_env = fake.deployments["frontend"]["containers"][0]["env"]
    patched_value = next(e["value"] for e in patched_env if e["name"] == "CART_SERVICE_ADDR")
    assert patched_value == "cartservice.does-not-resolve.invalid:7070"
    other_vars = [e for e in patched_env if e["name"] != "CART_SERVICE_ADDR"]
    prior_other_vars = [e for e in prior_env if e["name"] != "CART_SERVICE_ADDR"]
    assert other_vars == prior_other_vars


def test_revert_restores_prior_env() -> None:
    fake = FakeK8sClient()
    _seed_frontend(fake)
    scenario = DnsFailureScenario()
    snapshot = scenario.inject(fake, "frontend")

    scenario.revert(fake, "frontend", snapshot)

    reverted = fake.deployments["frontend"]["containers"][0]
    assert reverted == real_containers("frontend")[0]


def test_ground_truth_uses_fixed_service() -> None:
    gt = DnsFailureScenario().ground_truth("frontend")
    assert gt["affected_service"] == "frontend"
    assert "DNS" in gt["root_cause_label"]
