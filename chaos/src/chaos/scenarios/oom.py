from typing import Any, ClassVar

from chaos.scenarios.base import Scenario, load_definition


class OomScenario(Scenario):
    name: ClassVar[str] = "oom"
    requires_service: ClassVar[bool] = True

    def inject(self, k8s: Any, service: str) -> dict[str, Any]:
        definition = load_definition(self.name)
        new_limit = definition.default_params["memory_limit"]

        deployment = k8s.get_deployment(service)
        containers = deployment["containers"]
        container = next(c for c in containers if c["name"] == service)
        prior_resources = container["resources"]

        new_resources = {
            "limits": {**prior_resources["limits"], "memory": new_limit},
            "requests": dict(prior_resources["requests"]),
        }
        container["resources"] = new_resources
        k8s.patch_containers(service, containers)

        return {"resources": prior_resources}

    def revert(self, k8s: Any, service: str, saved_state: dict[str, Any]) -> None:
        deployment = k8s.get_deployment(service)
        containers = deployment["containers"]
        container = next(c for c in containers if c["name"] == service)
        container["resources"] = saved_state["resources"]
        k8s.patch_containers(service, containers)
