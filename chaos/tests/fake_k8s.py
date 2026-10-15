import copy
from typing import Any


class FakeK8sClient:
    """In-memory stand-in for chaos.k8s.K8sClient, used by scenario and CLI tests."""

    def __init__(self, namespace: str = "boutique") -> None:
        self.namespace = namespace
        self.deployments: dict[str, dict[str, Any]] = {}
        self.exec_calls: list[tuple[str, str, list[str]]] = []
        self.exec_responses: list[str] = []
        self.wait_calls: list[tuple[str, str, float]] = []

    def seed_deployment(self, name: str, containers: list[dict[str, Any]]) -> None:
        self.deployments[name] = {"containers": copy.deepcopy(containers)}

    def get_deployment(self, name: str) -> dict[str, Any]:
        return copy.deepcopy(self.deployments[name])

    def patch_containers(self, name: str, containers: list[dict[str, Any]]) -> None:
        self.deployments[name] = {"containers": copy.deepcopy(containers)}

    def exec_in_pod(self, pod_label_selector: str, container: str, command: list[str]) -> str:
        self.exec_calls.append((pod_label_selector, container, command))
        return self.exec_responses.pop(0) if self.exec_responses else ""

    def wait_for_container_ready(
        self, label_selector: str, container_name: str, timeout_seconds: float = 60
    ) -> None:
        self.wait_calls.append((label_selector, container_name, timeout_seconds))
