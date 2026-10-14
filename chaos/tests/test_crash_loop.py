from chaos.scenarios.crash_loop import CrashLoopScenario
from tests.fake_k8s import FakeK8sClient


def _seed_paymentservice(fake: FakeK8sClient) -> None:
    fake.seed_deployment(
        "paymentservice",
        [
            {
                "name": "paymentservice",
                "image": "repo/paymentservice:v0.10.7",
                "command": None,
                "env": [{"name": "PORT", "value": "50051"}, {"name": "DISABLE_PROFILER", "value": "1"}],
                "resources": {"limits": {"cpu": "200m", "memory": "128Mi"}, "requests": {"cpu": "100m", "memory": "64Mi"}},
            }
        ],
    )


def test_inject_overwrites_port_and_returns_prior_env():
    fake = FakeK8sClient()
    _seed_paymentservice(fake)
    scenario = CrashLoopScenario()

    snapshot = scenario.inject(fake, "paymentservice")

    assert snapshot == {
        "env": [{"name": "PORT", "value": "50051"}, {"name": "DISABLE_PROFILER", "value": "1"}]
    }
    patched_env = fake.deployments["paymentservice"]["containers"][0]["env"]
    assert {"name": "PORT", "value": "not-a-port"} in patched_env
    assert {"name": "DISABLE_PROFILER", "value": "1"} in patched_env


def test_revert_restores_prior_env():
    fake = FakeK8sClient()
    _seed_paymentservice(fake)
    scenario = CrashLoopScenario()
    snapshot = scenario.inject(fake, "paymentservice")

    scenario.revert(fake, "paymentservice", snapshot)

    assert fake.deployments["paymentservice"]["containers"][0]["env"] == [
        {"name": "PORT", "value": "50051"},
        {"name": "DISABLE_PROFILER", "value": "1"},
    ]


def test_ground_truth_fixed_to_paymentservice():
    gt = CrashLoopScenario().ground_truth("ignored")
    assert gt["affected_service"] == "paymentservice"
    assert "PORT" in gt["expected_fix"]
