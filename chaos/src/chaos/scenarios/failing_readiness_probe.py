from typing import Any, ClassVar

from chaos.scenarios.base import Scenario, load_definition


class FailingReadinessProbeScenario(Scenario):
    name: ClassVar[str] = "failing_readiness_probe"
    requires_service: ClassVar[bool] = True

    def inject(self, k8s: Any, service: str) -> dict[str, Any]:
        definition = load_definition(self.name)
        bad_path = definition.default_params["bad_probe_path"]

        deployment = k8s.get_deployment(service)
        containers = deployment["containers"]
        container = containers[0]
        prior_probe = container["readinessProbe"]

        container["readinessProbe"] = {
            **prior_probe,
            "httpGet": {**prior_probe["httpGet"], "path": bad_path},
        }
        k8s.patch_containers(service, containers)

        return {"readinessProbe": prior_probe}

    def revert(self, k8s: Any, service: str, saved_state: dict[str, Any]) -> None:
        deployment = k8s.get_deployment(service)
        containers = deployment["containers"]
        containers[0]["readinessProbe"] = saved_state["readinessProbe"]
        k8s.patch_containers(service, containers)
