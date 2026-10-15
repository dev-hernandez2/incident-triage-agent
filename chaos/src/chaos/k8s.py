import time
from typing import Any

from kubernetes import client, config


class K8sClient:
    def __init__(self, namespace: str = "boutique") -> None:
        config.load_kube_config()  # type: ignore[no-untyped-call]
        self._apps = client.AppsV1Api()
        self._core = client.CoreV1Api()
        self.namespace = namespace

    def get_deployment(self, name: str) -> dict[str, Any]:
        deployment = self._apps.read_namespaced_deployment(name=name, namespace=self.namespace)
        assert deployment.spec is not None
        pod_spec = deployment.spec.template.spec
        assert pod_spec is not None
        containers = pod_spec.containers
        serialized = self._apps.api_client.sanitize_for_serialization(containers)
        return {"containers": serialized}

    def patch_containers(self, name: str, containers: list[dict[str, Any]]) -> None:
        body = {"spec": {"template": {"spec": {"containers": containers}}}}
        self._apps.patch_namespaced_deployment(
            name=name,
            namespace=self.namespace,
            body=body,
            _content_type="application/merge-patch+json",
        )

    def exec_in_pod(self, pod_label_selector: str, container: str, command: list[str]) -> str:
        from kubernetes.stream import stream

        pods = self._core.list_namespaced_pod(
            namespace=self.namespace, label_selector=pod_label_selector
        )
        running = [p for p in pods.items if p.status is not None and p.status.phase == "Running"]
        if not running:
            raise RuntimeError(
                f"no Running pod matching {pod_label_selector!r} in namespace {self.namespace!r}"
            )
        pod_metadata = running[0].metadata
        assert pod_metadata is not None
        pod_name = pod_metadata.name
        result = stream(
            self._core.connect_get_namespaced_pod_exec,
            name=pod_name,
            namespace=self.namespace,
            container=container,
            command=command,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
        )
        return str(result)

    def wait_for_container_ready(
        self, label_selector: str, container_name: str, timeout_seconds: float = 60
    ) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            pods = self._core.list_namespaced_pod(
                namespace=self.namespace, label_selector=label_selector
            )
            for pod in pods.items:
                if pod.status is None or pod.status.phase != "Running":
                    continue
                for status in pod.status.container_statuses or []:
                    if status.name == container_name and status.ready:
                        return
            time.sleep(2)
        raise TimeoutError(
            f"no ready {container_name!r} container matching "
            f"{label_selector!r} within {timeout_seconds}s"
        )
