from boutique_manifest import real_containers
from chaos.scenarios.crash_loop import CrashLoopScenario
from fake_k8s import FakeK8sClient


def _seed_paymentservice(fake: FakeK8sClient) -> None:
    fake.seed_deployment("paymentservice", real_containers("paymentservice"))


def test_inject_overwrites_port_and_returns_prior_env() -> None:
    fake = FakeK8sClient()
    _seed_paymentservice(fake)
    scenario = CrashLoopScenario()

    snapshot = scenario.inject(fake, "paymentservice")

    assert snapshot == {
        "env": [{"name": "PORT", "value": "50051"}, {"name": "DISABLE_PROFILER", "value": "1"}]
    }
    patched = fake.deployments["paymentservice"]["containers"][0]
    assert patched["name"] == "server"
    assert {"name": "PORT", "value": "not-a-port"} in patched["env"]
    assert {"name": "DISABLE_PROFILER", "value": "1"} in patched["env"]
    # fields outside the env/resources/image/command set must survive untouched
    assert patched["readinessProbe"] == {"grpc": {"port": 50051}}
    assert patched["securityContext"]["readOnlyRootFilesystem"] is True


def test_revert_restores_prior_env() -> None:
    fake = FakeK8sClient()
    _seed_paymentservice(fake)
    scenario = CrashLoopScenario()
    snapshot = scenario.inject(fake, "paymentservice")

    scenario.revert(fake, "paymentservice", snapshot)

    reverted = fake.deployments["paymentservice"]["containers"][0]
    assert reverted["env"] == [
        {"name": "PORT", "value": "50051"},
        {"name": "DISABLE_PROFILER", "value": "1"},
    ]
    assert reverted == real_containers("paymentservice")[0]


def test_ground_truth_fixed_to_paymentservice() -> None:
    gt = CrashLoopScenario().ground_truth("ignored")
    assert gt["affected_service"] == "paymentservice"
    assert "PORT" in gt["expected_fix"]
