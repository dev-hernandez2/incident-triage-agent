from chaos.scenarios.slow_redis import SlowRedisScenario
from fake_k8s import FakeK8sClient


def _seed_redis_cart(fake: FakeK8sClient) -> None:
    fake.seed_deployment(
        "redis-cart",
        [
            {
                "name": "redis-cart",
                "image": "redis:alpine",
                "command": None,
                "env": [],
                "resources": {
                    "limits": {"cpu": "125m", "memory": "256Mi"},
                    "requests": {"cpu": "70m", "memory": "200Mi"},
                },
            }
        ],
    )


def test_inject_adds_toxiproxy_sidecar_and_shifts_redis_port() -> None:
    fake = FakeK8sClient()
    _seed_redis_cart(fake)
    scenario = SlowRedisScenario()

    snapshot = scenario.inject(fake, "redis-cart")

    assert snapshot == {
        "containers": [
            {
                "name": "redis-cart",
                "image": "redis:alpine",
                "command": None,
                "env": [],
                "resources": {
                    "limits": {"cpu": "125m", "memory": "256Mi"},
                    "requests": {"cpu": "70m", "memory": "200Mi"},
                },
            }
        ]
    }

    containers = fake.deployments["redis-cart"]["containers"]
    assert len(containers) == 2
    redis_container = next(c for c in containers if c["name"] == "redis-cart")
    assert redis_container["command"] == ["redis-server", "--port", "6380"]
    toxiproxy_container = next(c for c in containers if c["name"] == "toxiproxy")
    assert toxiproxy_container["image"] == "ghcr.io/shopify/toxiproxy:2.9.0"

    assert fake.exec_calls == [
        (
            "app=redis-cart",
            "toxiproxy",
            [
                "toxiproxy-cli",
                "create",
                "redis",
                "-l",
                "0.0.0.0:6379",
                "-u",
                "127.0.0.1:6380",
            ],
        ),
        (
            "app=redis-cart",
            "toxiproxy",
            ["toxiproxy-cli", "toxic", "add", "redis", "-t", "latency", "-a", "latency=2000"],
        ),
    ]


def test_revert_restores_single_container_and_original_command() -> None:
    fake = FakeK8sClient()
    _seed_redis_cart(fake)
    scenario = SlowRedisScenario()
    snapshot = scenario.inject(fake, "redis-cart")

    scenario.revert(fake, "redis-cart", snapshot)

    assert fake.deployments["redis-cart"]["containers"] == [
        {
            "name": "redis-cart",
            "image": "redis:alpine",
            "command": None,
            "env": [],
            "resources": {
                "limits": {"cpu": "125m", "memory": "256Mi"},
                "requests": {"cpu": "70m", "memory": "200Mi"},
            },
        }
    ]


def test_ground_truth_fixed_to_redis_cart() -> None:
    gt = SlowRedisScenario().ground_truth("ignored")
    assert gt["affected_service"] == "redis-cart"
    assert "latency" in gt["root_cause_label"]
