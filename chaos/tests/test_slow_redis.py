from boutique_manifest import real_containers
from chaos.scenarios.slow_redis import SlowRedisScenario
from fake_k8s import FakeK8sClient


def _seed_redis_cart(fake: FakeK8sClient) -> None:
    fake.seed_deployment("redis-cart", real_containers("redis-cart"))


def test_inject_adds_toxiproxy_sidecar_and_shifts_redis_port() -> None:
    fake = FakeK8sClient()
    _seed_redis_cart(fake)
    scenario = SlowRedisScenario()
    prior_redis_container = real_containers("redis-cart")[0]

    snapshot = scenario.inject(fake, "redis-cart")

    assert snapshot == {"containers": [prior_redis_container]}

    containers = fake.deployments["redis-cart"]["containers"]
    assert len(containers) == 2
    redis_container = next(c for c in containers if c["name"] == "redis")
    assert redis_container["command"] == ["redis-server", "--port", "6380"]
    # every other field from the real manifest must survive untouched
    assert redis_container["readinessProbe"] == prior_redis_container["readinessProbe"]
    assert redis_container["securityContext"] == prior_redis_container["securityContext"]
    assert redis_container["volumeMounts"] == prior_redis_container["volumeMounts"]

    toxiproxy_container = next(c for c in containers if c["name"] == "toxiproxy")
    assert toxiproxy_container["image"] == "ghcr.io/shopify/toxiproxy:2.9.0"
    assert toxiproxy_container["securityContext"] == {
        "allowPrivilegeEscalation": False,
        "capabilities": {"drop": ["ALL"]},
        "privileged": False,
        "readOnlyRootFilesystem": True,
    }

    # the new toxiproxy container must be confirmed ready before any exec,
    # since patch_namespaced_deployment returns before the new pod exists
    assert fake.wait_calls == [("app=redis-cart", "toxiproxy", 60)]

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


def test_revert_restores_single_container_with_every_original_field() -> None:
    fake = FakeK8sClient()
    _seed_redis_cart(fake)
    scenario = SlowRedisScenario()
    snapshot = scenario.inject(fake, "redis-cart")

    scenario.revert(fake, "redis-cart", snapshot)

    containers = fake.deployments["redis-cart"]["containers"]
    # the merge-patch-replace must drop toxiproxy entirely, not just leave
    # it alongside a reverted redis container
    assert containers == [real_containers("redis-cart")[0]]


def test_revert_clears_the_command_override_entirely() -> None:
    """The real redis container has no 'command' key at all; revert must
    not merely leave it unset in the patch (which an older strategic-merge
    patch would interpret as 'leave the cluster's current value alone'),
    it must land back on a container with no command override."""
    fake = FakeK8sClient()
    _seed_redis_cart(fake)
    scenario = SlowRedisScenario()
    snapshot = scenario.inject(fake, "redis-cart")
    assert fake.deployments["redis-cart"]["containers"][0]["command"] == [
        "redis-server",
        "--port",
        "6380",
    ]

    scenario.revert(fake, "redis-cart", snapshot)

    reverted = fake.deployments["redis-cart"]["containers"][0]
    assert "command" not in reverted


def test_ground_truth_fixed_to_redis_cart() -> None:
    gt = SlowRedisScenario().ground_truth("ignored")
    assert gt["affected_service"] == "redis-cart"
    assert "latency" in gt["root_cause_label"]
