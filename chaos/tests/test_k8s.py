from typing import Any
from unittest.mock import MagicMock, patch

from chaos.k8s import K8sClient


def _fake_v1_container(
    name: str,
    image: str,
    command: list[str] | None,
    env: dict[str, str],
    resources: dict[str, Any],
) -> MagicMock:
    c = MagicMock()
    c.name = name
    c.image = image
    c.command = command
    c.env = [MagicMock(name=k, value=v) for k, v in (env or {}).items()]
    for i, (k, v) in enumerate(env.items()):
        c.env[i].name = k
        c.env[i].value = v
    c.resources.limits = resources.get("limits")
    c.resources.requests = resources.get("requests")
    return c


def test_get_deployment_converts_to_plain_dict() -> None:
    container = _fake_v1_container(
        name="paymentservice",
        image="repo/paymentservice:v0.10.7",
        command=None,
        env={"PORT": "50051"},
        resources={
            "limits": {"cpu": "200m", "memory": "128Mi"},
            "requests": {"cpu": "100m", "memory": "64Mi"},
        },
    )
    deployment = MagicMock()
    deployment.spec.template.spec.containers = [container]

    fake_api = MagicMock()
    fake_api.read_namespaced_deployment.return_value = deployment

    with patch("chaos.k8s.client.AppsV1Api", return_value=fake_api), \
         patch("chaos.k8s.config.load_kube_config"):
        k8s = K8sClient(namespace="boutique")
        result = k8s.get_deployment("paymentservice")

    assert result == {
        "containers": [
            {
                "name": "paymentservice",
                "image": "repo/paymentservice:v0.10.7",
                "command": None,
                "env": [{"name": "PORT", "value": "50051"}],
                "resources": {
                    "limits": {"cpu": "200m", "memory": "128Mi"},
                    "requests": {"cpu": "100m", "memory": "64Mi"},
                },
            }
        ]
    }
    fake_api.read_namespaced_deployment.assert_called_once_with(
        name="paymentservice", namespace="boutique"
    )
