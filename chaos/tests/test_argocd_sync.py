import httpx
import pytest
from chaos.argocd_sync import ArgoCdClient, ArgoCdSyncTimeoutError
from fake_argocd import FakeArgoCdTransport


def _client(transport: FakeArgoCdTransport) -> ArgoCdClient:
    http_client = httpx.Client(transport=transport, base_url="http://argocd.local")
    return ArgoCdClient(
        base_url="http://argocd.local",
        app_name="boutique",
        token="fake-token",
        http_client=http_client,
    )


def test_current_sync_revision_reads_from_api() -> None:
    transport = FakeArgoCdTransport()
    transport.synced_revision = "a" * 40
    client = _client(transport)

    assert client.current_sync_revision() == "a" * 40


def test_wait_for_sync_succeeds_after_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    transport = FakeArgoCdTransport()
    transport.set_synced_after("b" * 40, polls=3)
    client = _client(transport)

    client.wait_for_sync(target_revision="b" * 40, timeout_s=10, poll_interval_s=0)

    assert client.current_sync_revision() == "b" * 40


def test_wait_for_sync_raises_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    transport = FakeArgoCdTransport()
    transport.set_synced_after("c" * 40, polls=1_000_000)  # never catches up
    client = _client(transport)

    with pytest.raises(ArgoCdSyncTimeoutError):
        client.wait_for_sync(target_revision="c" * 40, timeout_s=0.01, poll_interval_s=0)
