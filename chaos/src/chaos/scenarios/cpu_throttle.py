from typing import Any, ClassVar

from chaos.scenarios.base import Scenario, load_definition


class CpuThrottleScenario(Scenario):
    name: ClassVar[str] = "cpu_throttle"
    requires_service: ClassVar[bool] = True

    def inject(self, k8s: Any, service: str) -> dict[str, Any]:
        definition = load_definition(self.name)
        new_limit = definition.default_params["cpu_limit"]

        deployment = k8s.get_deployment(service)
        containers = deployment["containers"]
        container = containers[0]
        prior_resources = container["resources"]

        container["resources"] = {
            "limits": {**prior_resources["limits"], "cpu": new_limit},
            "requests": dict(prior_resources["requests"]),
        }
        k8s.patch_containers(service, containers)

        return {"resources": prior_resources}

    def revert(self, k8s: Any, service: str, saved_state: dict[str, Any]) -> None:
        deployment = k8s.get_deployment(service)
        containers = deployment["containers"]
        containers[0]["resources"] = saved_state["resources"]
        k8s.patch_containers(service, containers)
