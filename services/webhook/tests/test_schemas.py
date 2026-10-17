"""Tests for Alertmanager payload parsing and mapping to the internal message schema."""

from typing import Any

import pytest
from pydantic import ValidationError
from webhook.schemas import AlertmanagerWebhookPayload, to_alert_message

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


def test_valid_payload_parses() -> None:
    payload = AlertmanagerWebhookPayload.model_validate(VALID_PAYLOAD)
    assert len(payload.alerts) == 1
    assert payload.alerts[0].fingerprint == "abc123"


def test_multi_alert_payload_parses_all_alerts() -> None:
    payload_dict = {**VALID_PAYLOAD, "alerts": VALID_PAYLOAD["alerts"] * 2}
    payload = AlertmanagerWebhookPayload.model_validate(payload_dict)
    assert len(payload.alerts) == 2


def test_missing_alerts_key_raises_validation_error() -> None:
    bad_payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "alerts"}
    with pytest.raises(ValidationError):
        AlertmanagerWebhookPayload.model_validate(bad_payload)


def test_to_alert_message_maps_fields() -> None:
    payload = AlertmanagerWebhookPayload.model_validate(VALID_PAYLOAD)
    message = to_alert_message(payload.alerts[0])
    assert message.fingerprint == "abc123"
    assert message.status == "firing"
    assert message.alertname == "BoutiquePodCrashLooping"
    assert message.labels == {
        "alertname": "BoutiquePodCrashLooping",
        "pod": "cartservice-abc",
        "namespace": "boutique",
    }
    assert message.annotations == {"summary": "Pod is crash looping"}
    assert message.starts_at == "2026-10-16T10:00:00Z"
