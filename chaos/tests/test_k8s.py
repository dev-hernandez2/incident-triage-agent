from typing import Any
from unittest.mock import MagicMock, patch

from chaos.k8s import K8sClient
from kubernetes import client as k8s_client


def _real_v1_deployment(containers: list[Any]) -> Any:
    return k8s_client.V1Deployment(
        spec=k8s_client.V1DeploymentSpec(
            selector=k8s_client.V1LabelSelector(),
            template=k8s_client.V1PodTemplateSpec(
                spec=k8s_client.V1PodSpec(containers=containers)
            ),
        )
    )


def test_get_deployment_preserves_fields_not_in_the_narrow_model() -> None:
    container = k8s_client.V1Container(
        name="redis",
        image="redis:alpine",
        ports=[k8s_client.V1ContainerPort(container_port=6379)],
        liveness_probe=k8s_client.V1Probe(
            tcp_socket=k8s_client.V1TCPSocketAction(port=6379), period_seconds=5
        ),
        security_context=k8s_client.V1SecurityContext(read_only_root_filesystem=True),
        resources=k8s_client.V1ResourceRequirements(
            limits={"cpu": "125m", "memory": "256Mi"},
            requests={"cpu": "70m", "memory": "200Mi"},
        ),
    )
    deployment = _real_v1_deployment([container])

    fake_api = MagicMock()
    fake_api.read_namespaced_deployment.return_value = deployment
    fake_api.api_client = k8s_client.ApiClient()

    with (
        patch("chaos.k8s.client.AppsV1Api", return_value=fake_api),
        patch("chaos.k8s.config.load_kube_config"),
    ):
        k8s = K8sClient(namespace="boutique")
        result = k8s.get_deployment("redis-cart")

    assert len(result["containers"]) == 1
    container_dict = result["containers"][0]
    assert container_dict["name"] == "redis"
    assert container_dict["image"] == "redis:alpine"
    assert container_dict["ports"] == [{"containerPort": 6379}]
    assert container_dict["livenessProbe"] == {
        "periodSeconds": 5,
        "tcpSocket": {"port": 6379},
    }
    assert container_dict["securityContext"] == {"readOnlyRootFilesystem": True}
    assert container_dict["resources"] == {
        "limits": {"cpu": "125m", "memory": "256Mi"},
        "requests": {"cpu": "70m", "memory": "200Mi"},
    }
    fake_api.read_namespaced_deployment.assert_called_once_with(
        name="redis-cart", namespace="boutique"
    )


def test_patch_containers_sends_whole_list_as_merge_patch() -> None:
    fake_api = MagicMock()

    with (
        patch("chaos.k8s.client.AppsV1Api", return_value=fake_api),
        patch("chaos.k8s.config.load_kube_config"),
    ):
        k8s = K8sClient(namespace="boutique")
        k8s.patch_containers(
            "redis-cart",
            [
                {"name": "redis", "image": "redis:alpine"},
                {"name": "toxiproxy", "image": "ghcr.io/shopify/toxiproxy:2.9.0"},
            ],
        )

    fake_api.patch_namespaced_deployment.assert_called_once_with(
        name="redis-cart",
        namespace="boutique",
        body={
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {"name": "redis", "image": "redis:alpine"},
                            {"name": "toxiproxy", "image": "ghcr.io/shopify/toxiproxy:2.9.0"},
                        ]
                    }
                }
            }
        },
        _content_type="application/merge-patch+json",
    )


def test_patch_containers_replaces_list_so_removed_containers_disappear() -> None:
    """A JSON merge-patch replaces the whole containers array (unlike a
    strategic merge patch, which would keep an unmentioned container)."""
    fake_api = MagicMock()

    with (
        patch("chaos.k8s.client.AppsV1Api", return_value=fake_api),
        patch("chaos.k8s.config.load_kube_config"),
    ):
        k8s = K8sClient(namespace="boutique")
        k8s.patch_containers("redis-cart", [{"name": "redis", "image": "redis:alpine"}])

    call = fake_api.patch_namespaced_deployment.call_args
    assert call.kwargs["body"]["spec"]["template"]["spec"]["containers"] == [
        {"name": "redis", "image": "redis:alpine"}
    ]
    assert call.kwargs["_content_type"] == "application/merge-patch+json"


def _fake_pod(name: str, phase: str) -> MagicMock:
    pod = MagicMock()
    pod.metadata.name = name
    pod.status.phase = phase
    return pod


def test_exec_in_pod_skips_non_running_pods() -> None:
    """During a rollout, list_namespaced_pod can return the old
    Terminating pod ahead of the new Running one; items[0] would pick
    the wrong pod."""
    fake_core = MagicMock()
    fake_core.list_namespaced_pod.return_value.items = [
        _fake_pod("redis-cart-old-abc", "Terminating"),
        _fake_pod("redis-cart-new-def", "Running"),
    ]

    with (
        patch("chaos.k8s.client.CoreV1Api", return_value=fake_core),
        patch("chaos.k8s.config.load_kube_config"),
        patch("kubernetes.stream.stream", return_value="ok") as fake_stream,
    ):
        k8s = K8sClient(namespace="boutique")
        result = k8s.exec_in_pod("app=redis-cart", "toxiproxy", ["echo", "hi"])

    assert result == "ok"
    assert fake_stream.call_args.kwargs["name"] == "redis-cart-new-def"


def test_exec_in_pod_raises_clearly_when_no_pod_is_running() -> None:
    fake_core = MagicMock()
    fake_core.list_namespaced_pod.return_value.items = [
        _fake_pod("redis-cart-old-abc", "Terminating"),
    ]

    with (
        patch("chaos.k8s.client.CoreV1Api", return_value=fake_core),
        patch("chaos.k8s.config.load_kube_config"),
    ):
        k8s = K8sClient(namespace="boutique")
        try:
            k8s.exec_in_pod("app=redis-cart", "toxiproxy", ["echo", "hi"])
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "app=redis-cart" in str(exc)


def _fake_pod_with_container_status(phase: str, container_name: str, ready: bool) -> MagicMock:
    pod = MagicMock()
    pod.status.phase = phase
    status = MagicMock()
    status.name = container_name
    status.ready = ready
    pod.status.container_statuses = [status]
    return pod


def test_wait_for_container_ready_returns_once_ready() -> None:
    fake_core = MagicMock()
    fake_core.list_namespaced_pod.return_value.items = [
        _fake_pod_with_container_status("Running", "toxiproxy", ready=True)
    ]

    with (
        patch("chaos.k8s.client.CoreV1Api", return_value=fake_core),
        patch("chaos.k8s.config.load_kube_config"),
    ):
        k8s = K8sClient(namespace="boutique")
        k8s.wait_for_container_ready("app=redis-cart", "toxiproxy", timeout_seconds=5)

    fake_core.list_namespaced_pod.assert_called_with(
        namespace="boutique", label_selector="app=redis-cart"
    )


def test_wait_for_container_ready_times_out_with_a_clear_error() -> None:
    fake_core = MagicMock()
    fake_core.list_namespaced_pod.return_value.items = [
        _fake_pod_with_container_status("Running", "toxiproxy", ready=False)
    ]

    with (
        patch("chaos.k8s.client.CoreV1Api", return_value=fake_core),
        patch("chaos.k8s.config.load_kube_config"),
        patch("chaos.k8s.time.sleep"),
    ):
        k8s = K8sClient(namespace="boutique")
        try:
            k8s.wait_for_container_ready("app=redis-cart", "toxiproxy", timeout_seconds=0.01)
            assert False, "expected TimeoutError"
        except TimeoutError as exc:
            assert "toxiproxy" in str(exc)
            assert "app=redis-cart" in str(exc)
