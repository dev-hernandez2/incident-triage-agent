from typing import Any, ClassVar

from chaos.scenarios.base import Scenario, load_definition

_TARGET_DEPLOYMENT = "frontend"


class DnsFailureScenario(Scenario):
    name: ClassVar[str] = "dns_failure"
    requires_service: ClassVar[bool] = False

    def inject(self, k8s: Any, service: str) -> dict[str, Any]:
        definition = load_definition(self.name)
        target_var = definition.default_params["target_env_var"]
        bad_hostname = definition.default_params["bad_hostname"]

        deployment = k8s.get_deployment(_TARGET_DEPLOYMENT)
        containers = deployment["containers"]
        container = containers[0]
        prior_env = container.get("env", [])

        container["env"] = [
            {"name": target_var, "value": bad_hostname} if e["name"] == target_var else e
            for e in prior_env
        ]
        k8s.patch_containers(_TARGET_DEPLOYMENT, containers)

        return {"env": prior_env}

    def revert(self, k8s: Any, service: str, saved_state: dict[str, Any]) -> None:
        deployment = k8s.get_deployment(_TARGET_DEPLOYMENT)
        containers = deployment["containers"]
        containers[0]["env"] = saved_state["env"]
        k8s.patch_containers(_TARGET_DEPLOYMENT, containers)
