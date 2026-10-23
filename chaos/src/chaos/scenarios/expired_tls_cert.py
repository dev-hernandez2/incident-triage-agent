from typing import Any, ClassVar

from chaos.scenarios.base import Scenario, load_definition


class ExpiredTlsCertScenario(Scenario):
    name: ClassVar[str] = "expired_tls_cert"
    requires_service: ClassVar[bool] = False

    def inject(self, k8s: Any, service: str) -> dict[str, Any]:
        definition = load_definition(self.name)
        secret_name = definition.default_params["secret_name"]
        expired_cert = definition.default_params["expired_cert_pem"]

        prior_secret = k8s.get_secret(secret_name)
        k8s.patch_secret(secret_name, {**prior_secret, "tls.crt": expired_cert})

        return dict(prior_secret)

    def revert(self, k8s: Any, service: str, saved_state: dict[str, Any]) -> None:
        definition = load_definition(self.name)
        secret_name = definition.default_params["secret_name"]
        k8s.patch_secret(secret_name, saved_state)
