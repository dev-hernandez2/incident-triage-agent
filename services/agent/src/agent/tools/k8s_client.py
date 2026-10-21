"""Read-only Kubernetes client wrapper, namespace-allow-listed.

Deliberately exposes no mutating operations (no patch/delete/create/exec) —
the agent's RBAC ClusterRole also only grants get/list/watch, but this keeps
the agent's own code from ever attempting a write. See deploy/k8s/rbac-triage-agent.yaml.
"""

from typing import Any

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

from agent.tools.base import ToolError


class NamespaceNotAllowedError(ToolError):
    pass


class K8sReadOnlyClient:
    def __init__(self, allowed_namespaces: frozenset[str]) -> None:
        self.allowed_namespaces = allowed_namespaces
        self._apps: Any = None
        self._core: Any = None

    def _ensure_configured(self) -> None:
        # Deferred from __init__ so constructing a K8sReadOnlyClient (e.g. to
        # read tool names/schemas without ever calling a tool, as the eval
        # harness's replay mode does) never requires a live cluster or a
        # kubeconfig file on disk. The live agent still fails fast here, on
        # its first real API call, if it's actually misconfigured.
        if self._apps is not None:
            return
        try:
            config.load_incluster_config()  # type: ignore[no-untyped-call]
        except config.ConfigException:
            config.load_kube_config()  # type: ignore[no-untyped-call]
        self._apps = client.AppsV1Api()
        self._core = client.CoreV1Api()

    def _check_namespace(self, namespace: str) -> None:
        if namespace not in self.allowed_namespaces:
            allow_list = sorted(self.allowed_namespaces)
            raise NamespaceNotAllowedError(
                f"namespace {namespace!r} is not in the allow-list {allow_list}"
            )

    def describe_pod(self, name: str, namespace: str) -> dict[str, Any]:
        self._ensure_configured()
        self._check_namespace(namespace)
        try:
            pod = self._core.read_namespaced_pod(name=name, namespace=namespace)
        except ApiException as exc:
            raise ToolError(f"failed to read pod {name!r}: {exc.reason}") from exc
        result: dict[str, Any] = self._core.api_client.sanitize_for_serialization(pod)
        return result

    def describe_deployment(self, name: str, namespace: str) -> dict[str, Any]:
        self._ensure_configured()
        self._check_namespace(namespace)
        try:
            deployment = self._apps.read_namespaced_deployment(name=name, namespace=namespace)
        except ApiException as exc:
            raise ToolError(f"failed to read deployment {name!r}: {exc.reason}") from exc
        result: dict[str, Any] = self._apps.api_client.sanitize_for_serialization(deployment)
        return result

    def get_events(self, namespace: str) -> list[dict[str, Any]]:
        self._ensure_configured()
        self._check_namespace(namespace)
        try:
            events = self._core.list_namespaced_event(namespace=namespace)
        except ApiException as exc:
            raise ToolError(f"failed to list events in {namespace!r}: {exc.reason}") from exc
        items: list[dict[str, Any]] = self._core.api_client.sanitize_for_serialization(
            events.items
        )
        return items

    def list_pods(self, namespace: str, selector: str | None) -> list[dict[str, Any]]:
        self._ensure_configured()
        self._check_namespace(namespace)
        try:
            pods = self._core.list_namespaced_pod(
                namespace=namespace, label_selector=selector or ""
            )
        except ApiException as exc:
            raise ToolError(f"failed to list pods in {namespace!r}: {exc.reason}") from exc
        items: list[dict[str, Any]] = self._core.api_client.sanitize_for_serialization(pods.items)
        return items
