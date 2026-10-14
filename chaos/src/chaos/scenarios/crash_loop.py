from typing import Any, ClassVar

from chaos.scenarios.base import Scenario, load_definition

_TARGET_DEPLOYMENT = "paymentservice"
_CONTAINER_NAME = "paymentservice"


class CrashLoopScenario(Scenario):
    name: ClassVar[str] = "crash_loop"
    requires_service: ClassVar[bool] = False

    def inject(self, k8s: Any, service: str) -> dict[str, Any]:
        definition = load_definition(self.name)
        bad_value = definition.default_params["bad_port_value"]

        deployment = k8s.get_deployment(_TARGET_DEPLOYMENT)
        containers = deployment["containers"]
        container = next(c for c in containers if c["name"] == _CONTAINER_NAME)
        prior_env = container["env"]

        new_env = [
            {"name": "PORT", "value": bad_value} if e["name"] == "PORT" else e
            for e in prior_env
        ]
        container["env"] = new_env
        k8s.patch_containers(_TARGET_DEPLOYMENT, containers)

        return {"env": prior_env}

    def revert(self, k8s: Any, service: str, saved_state: dict[str, Any]) -> None:
        deployment = k8s.get_deployment(_TARGET_DEPLOYMENT)
        containers = deployment["containers"]
        container = next(c for c in containers if c["name"] == _CONTAINER_NAME)
        container["env"] = saved_state["env"]
        k8s.patch_containers(_TARGET_DEPLOYMENT, containers)
