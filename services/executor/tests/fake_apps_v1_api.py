"""In-memory fake of the kubernetes AppsV1Api surface the executor needs."""

from typing import Any


class FakeAppsV1Api:
    def __init__(self) -> None:
        self.patches: list[tuple[str, str, dict[str, Any]]] = []

    def patch_namespaced_deployment(
        self, name: str, namespace: str, body: dict[str, Any], **kwargs: object
    ) -> None:
        self.patches.append((name, namespace, body))
