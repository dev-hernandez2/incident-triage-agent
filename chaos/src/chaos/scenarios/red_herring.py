from typing import Any, ClassVar

from chaos.scenarios.base import Scenario, load_definition

_CAUSAL_DEPLOYMENT = "checkoutservice"
_SYMPTOM_DEPLOYMENT = "frontend"


class RedHerringScenario(Scenario):
    """Breaks checkoutservice (the real cause) and simultaneously bumps
    frontend's restart count (a plausible but non-causal symptom), so the
    agent must identify checkoutservice, not frontend, as the root cause."""

    name: ClassVar[str] = "red_herring"
    requires_service: ClassVar[bool] = False

    def inject(self, k8s: Any, service: str) -> dict[str, Any]:
        definition = load_definition(self.name)
        bad_value = definition.default_params["bad_port_value"]

        causal_deployment = k8s.get_deployment(_CAUSAL_DEPLOYMENT)
        causal_containers = causal_deployment["containers"]
        causal_prior_env = causal_containers[0].get("env", [])
        causal_containers[0]["env"] = [
            {"name": "PORT", "value": bad_value} if e["name"] == "PORT" else e
            for e in causal_prior_env
        ]
        k8s.patch_containers(_CAUSAL_DEPLOYMENT, causal_containers)

        symptom_deployment = k8s.get_deployment(_SYMPTOM_DEPLOYMENT)
        symptom_containers = symptom_deployment["containers"]
        k8s.patch_containers(_SYMPTOM_DEPLOYMENT, symptom_containers)

        return {
            "checkoutservice": {"env": causal_prior_env},
            "frontend": {"containers": symptom_deployment["containers"]},
        }

    def revert(self, k8s: Any, service: str, saved_state: dict[str, Any]) -> None:
        causal_deployment = k8s.get_deployment(_CAUSAL_DEPLOYMENT)
        causal_containers = causal_deployment["containers"]
        causal_containers[0]["env"] = saved_state["checkoutservice"]["env"]
        k8s.patch_containers(_CAUSAL_DEPLOYMENT, causal_containers)

        k8s.patch_containers(_SYMPTOM_DEPLOYMENT, saved_state["frontend"]["containers"])
