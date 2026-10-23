from typing import Any, ClassVar

from chaos.scenarios.base import Scenario, load_definition

_LABEL_SELECTOR = "app=cartservice"


class PromptInjectionScenario(Scenario):
    """Injects a real fault (OOM) and writes an embedded instruction to the
    pod's own stdout, so search_logs surfaces it to the agent only as
    untrusted tool output — never as a message the agent itself sent."""

    name: ClassVar[str] = "prompt_injection"
    requires_service: ClassVar[bool] = False

    def inject(self, k8s: Any, service: str) -> dict[str, Any]:
        definition = load_definition(self.name)
        new_limit = definition.default_params["memory_limit"]
        instruction = definition.injected_instruction

        deployment = k8s.get_deployment("cartservice")
        containers = deployment["containers"]
        container = containers[0]
        prior_resources = container["resources"]

        container["resources"] = {
            "limits": {**prior_resources["limits"], "memory": new_limit},
            "requests": dict(prior_resources["requests"]),
        }
        k8s.patch_containers("cartservice", containers)

        k8s.exec_in_pod(
            _LABEL_SELECTOR,
            container["name"],
            ["sh", "-c", f"echo '{instruction}' >> /proc/1/fd/1"],
        )

        return {"resources": prior_resources}

    def revert(self, k8s: Any, service: str, saved_state: dict[str, Any]) -> None:
        deployment = k8s.get_deployment("cartservice")
        containers = deployment["containers"]
        containers[0]["resources"] = saved_state["resources"]
        k8s.patch_containers("cartservice", containers)
