from typing import Any, ClassVar

from chaos.scenarios.base import Scenario, load_definition

_TARGET_DEPLOYMENT = "redis-cart"
_LABEL_SELECTOR = "app=redis-cart"

# toxiproxy-server keeps its state in memory and is configured entirely
# through its admin API, so it needs no writable filesystem; this mirrors
# the redis container's own least-privilege securityContext rather than
# falling back to the pod's defaults.
_TOXIPROXY_SECURITY_CONTEXT = {
    "allowPrivilegeEscalation": False,
    "capabilities": {"drop": ["ALL"]},
    "privileged": False,
    "readOnlyRootFilesystem": True,
}


class SlowRedisScenario(Scenario):
    name: ClassVar[str] = "slow_redis"
    requires_service: ClassVar[bool] = False

    def inject(self, k8s: Any, service: str) -> dict[str, Any]:
        definition = load_definition(self.name)
        internal_port = definition.default_params["redis_internal_port"]
        toxiproxy_image = definition.default_params["toxiproxy_image"]
        latency_ms = definition.default_params["latency_ms"]

        deployment = k8s.get_deployment(_TARGET_DEPLOYMENT)
        prior_containers = deployment["containers"]

        redis_container = dict(prior_containers[0])
        redis_container["command"] = ["redis-server", "--port", internal_port]
        toxiproxy_container = {
            "name": "toxiproxy",
            "image": toxiproxy_image,
            "securityContext": dict(_TOXIPROXY_SECURITY_CONTEXT),
        }

        k8s.patch_containers(_TARGET_DEPLOYMENT, [redis_container, toxiproxy_container])

        # patch_namespaced_deployment returns as soon as the Deployment
        # object is updated, before the new pod exists, so exec_in_pod
        # below would otherwise hit the old pod (no toxiproxy container
        # yet) or find no pod at all.
        k8s.wait_for_container_ready(_LABEL_SELECTOR, "toxiproxy")

        k8s.exec_in_pod(
            _LABEL_SELECTOR,
            "toxiproxy",
            [
                "toxiproxy-cli",
                "create",
                "redis",
                "-l",
                "0.0.0.0:6379",
                "-u",
                f"127.0.0.1:{internal_port}",
            ],
        )
        k8s.exec_in_pod(
            _LABEL_SELECTOR,
            "toxiproxy",
            [
                "toxiproxy-cli",
                "toxic",
                "add",
                "redis",
                "-t",
                "latency",
                "-a",
                f"latency={latency_ms}",
            ],
        )

        return {"containers": prior_containers}

    def revert(self, k8s: Any, service: str, saved_state: dict[str, Any]) -> None:
        k8s.patch_containers(_TARGET_DEPLOYMENT, saved_state["containers"])
