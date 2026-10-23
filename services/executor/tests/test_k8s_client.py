from executor.k8s_client import K8sExecutorClient
from fake_apps_v1_api import FakeAppsV1Api


def _client_with_fake(fake: FakeAppsV1Api) -> K8sExecutorClient:
    client = K8sExecutorClient(allowed_namespace="boutique")
    client._apps = fake
    return client


def test_restart_patches_restarted_at_annotation() -> None:
    fake = FakeAppsV1Api()
    client = _client_with_fake(fake)

    client.restart("cartservice")

    assert len(fake.patches) == 1
    name, namespace, body = fake.patches[0]
    assert name == "cartservice"
    assert namespace == "boutique"
    annotations = body["spec"]["template"]["metadata"]["annotations"]
    assert "kubectl.kubernetes.io/restartedAt" in annotations


def test_scale_patches_replicas() -> None:
    fake = FakeAppsV1Api()
    client = _client_with_fake(fake)

    client.scale("checkoutservice", replicas=5)

    assert len(fake.patches) == 1
    name, namespace, body = fake.patches[0]
    assert name == "checkoutservice"
    assert namespace == "boutique"
    assert body["spec"]["replicas"] == 5


def test_rollback_patches_revision_annotation() -> None:
    fake = FakeAppsV1Api()
    client = _client_with_fake(fake)

    client.rollback("cartservice")

    assert len(fake.patches) == 1
    name, namespace, body = fake.patches[0]
    assert name == "cartservice"
    assert namespace == "boutique"
    assert "spec" in body
