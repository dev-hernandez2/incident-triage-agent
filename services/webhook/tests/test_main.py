"""Tests for the /alerts and /healthz endpoints, with a fake Kafka producer."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from webhook.main import app, get_producer
from webhook.schemas import AlertMessage

VALID_PAYLOAD: dict[str, Any] = {
    "version": "4",
    "groupKey": "{}:{alertname=\"BoutiquePodCrashLooping\"}",
    "status": "firing",
    "receiver": "webhook",
    "alerts": [
        {
            "status": "firing",
            "labels": {
                "alertname": "BoutiquePodCrashLooping",
                "pod": "cartservice-abc",
                "namespace": "boutique",
            },
            "annotations": {"summary": "Pod is crash looping"},
            "startsAt": "2026-10-16T10:00:00Z",
            "endsAt": "0001-01-01T00:00:00Z",
            "fingerprint": "abc123",
        }
    ],
}


class FakeProducer:
    def __init__(self) -> None:
        self.produced: list[AlertMessage] = []
        self.healthy = True

    def produce(self, message: AlertMessage) -> None:
        self.produced.append(message)

    def healthcheck(self) -> bool:
        return self.healthy


class FailingProducer(FakeProducer):
    def produce(self, message: AlertMessage) -> None:
        raise RuntimeError("broker unreachable")


@pytest.fixture
def fake_producer() -> FakeProducer:
    return FakeProducer()


@pytest.fixture
def client(fake_producer: FakeProducer) -> Any:
    app.dependency_overrides[get_producer] = lambda: fake_producer
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_post_alerts_produces_one_message_per_alert(
    client: Any, fake_producer: FakeProducer
) -> None:
    response = client.post("/alerts", json=VALID_PAYLOAD)
    assert response.status_code == 200
    assert response.json() == {"accepted": 1}
    assert len(fake_producer.produced) == 1
    assert fake_producer.produced[0].fingerprint == "abc123"


def test_post_alerts_multiple_alerts_produces_multiple_messages(
    client: Any, fake_producer: FakeProducer
) -> None:
    payload = {**VALID_PAYLOAD, "alerts": [
        {**VALID_PAYLOAD["alerts"][0], "fingerprint": "abc123"},
        {**VALID_PAYLOAD["alerts"][0], "fingerprint": "def456"},
    ]}
    response = client.post("/alerts", json=payload)
    assert response.status_code == 200
    assert response.json() == {"accepted": 2}
    assert len(fake_producer.produced) == 2


def test_post_alerts_malformed_payload_returns_422(client: Any) -> None:
    response = client.post("/alerts", json={"not": "valid"})
    assert response.status_code == 422


def test_post_alerts_producer_failure_returns_5xx(fake_producer: FakeProducer) -> None:
    app.dependency_overrides[get_producer] = lambda: FailingProducer()
    with TestClient(app) as test_client:
        response = test_client.post("/alerts", json=VALID_PAYLOAD)
    app.dependency_overrides.clear()
    assert response.status_code == 502


def test_healthz_ok(client: Any) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200


def test_healthz_unhealthy_producer_returns_503(fake_producer: FakeProducer) -> None:
    fake_producer.healthy = False
    app.dependency_overrides[get_producer] = lambda: fake_producer
    with TestClient(app) as test_client:
        response = test_client.get("/healthz")
    app.dependency_overrides.clear()
    assert response.status_code == 503
