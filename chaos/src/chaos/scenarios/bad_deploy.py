from typing import Any, ClassVar

from chaos.scenarios.base import Scenario, load_definition


class BadDeployScenario(Scenario):
    name: ClassVar[str] = "bad_deploy"
    requires_service: ClassVar[bool] = True

    def inject(self, k8s: Any, service: str) -> dict[str, Any]:
        definition = load_definition(self.name)
        bad_tag = definition.default_params["bad_tag"]

        deployment = k8s.get_deployment(service)
        containers = deployment["containers"]
        container = containers[0]
        prior_image = container["image"]

        repo = prior_image.rsplit(":", 1)[0]
        container["image"] = f"{repo}:{bad_tag}"
        k8s.patch_containers(service, containers)

        return {"image": prior_image}

    def revert(self, k8s: Any, service: str, saved_state: dict[str, Any]) -> None:
        deployment = k8s.get_deployment(service)
        containers = deployment["containers"]
        containers[0]["image"] = saved_state["image"]
        k8s.patch_containers(service, containers)
