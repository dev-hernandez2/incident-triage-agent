from boutique_manifest import real_containers
from chaos.scenarios.red_herring import RedHerringScenario
from fake_k8s import FakeK8sClient


def _seed(fake: FakeK8sClient) -> None:
    fake.seed_deployment("checkoutservice", real_containers("checkoutservice"))
    fake.seed_deployment("frontend", real_containers("frontend"))


def test_inject_breaks_causal_service_and_marks_symptom_service() -> None:
    fake = FakeK8sClient()
    _seed(fake)
    scenario = RedHerringScenario()

    snapshot = scenario.inject(fake, "checkoutservice")

    causal_env = fake.deployments["checkoutservice"]["containers"][0]["env"]
    port_value = next(e["value"] for e in causal_env if e["name"] == "PORT")
    assert port_value == "not-a-port"
    assert "checkoutservice" in snapshot
    assert "frontend" in snapshot


def test_revert_restores_both_services() -> None:
    fake = FakeK8sClient()
    _seed(fake)
    scenario = RedHerringScenario()
    snapshot = scenario.inject(fake, "checkoutservice")

    scenario.revert(fake, "checkoutservice", snapshot)

    assert fake.deployments["checkoutservice"]["containers"] == real_containers("checkoutservice")
    assert fake.deployments["frontend"]["containers"] == real_containers("frontend")


def test_ground_truth_names_causal_service_not_symptom_service() -> None:
    gt = RedHerringScenario().ground_truth("checkoutservice")
    assert gt["affected_service"] == "checkoutservice"
    assert "checkoutservice" in gt["root_cause_label"]
