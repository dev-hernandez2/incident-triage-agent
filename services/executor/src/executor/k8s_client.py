"""Namespace-scoped, mutating Kubernetes client. Only services/executor
may import this — it is the only service allowed to patch deployments.
See deploy/k8s/rbac-triage-executor.yaml for the matching RBAC Role.
"""

from datetime import UTC, datetime
from typing import Any

from kubernetes import client, config


class K8sExecutorClient:
    def __init__(self, allowed_namespace: str) -> None:
        self.allowed_namespace = allowed_namespace
        self._apps: Any = None

    def _ensure_configured(self) -> None:
        if self._apps is not None:
            return
        try:
            config.load_incluster_config()  # type: ignore[no-untyped-call]
        except config.ConfigException:
            config.load_kube_config()  # type: ignore[no-untyped-call]
        self._apps = client.AppsV1Api()

    def restart(self, deployment: str) -> None:
        self._ensure_configured()
        timestamp = datetime.now(UTC).isoformat()
        body = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {"kubectl.kubernetes.io/restartedAt": timestamp}
                    }
                }
            }
        }
        self._apps.patch_namespaced_deployment(
            name=deployment,
            namespace=self.allowed_namespace,
            body=body,
            _content_type="application/merge-patch+json",
        )

    def scale(self, deployment: str, replicas: int) -> None:
        self._ensure_configured()
        body = {"spec": {"replicas": replicas}}
        self._apps.patch_namespaced_deployment(
            name=deployment,
            namespace=self.allowed_namespace,
            body=body,
            _content_type="application/merge-patch+json",
        )

    def rollback(self, deployment: str) -> None:
        # Online Boutique's deployments are managed via Argo CD (see
        # deploy/k8s/argocd-boutique-app.yaml) — "rollback" here means
        # forcing a fresh rollout of the currently-synced manifest, which
        # is the same mechanism as restart. A true multi-revision rollback
        # (reverting to a prior ReplicaSet) would need the Deployment's
        # revision history, which a merge-patch can't address directly;
        # out of scope for this project (see spec's "Out of scope").
        self.restart(deployment)
