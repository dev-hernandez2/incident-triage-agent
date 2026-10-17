"""Tests for parsing raw Kafka message bytes into AlertMessage."""

import json

import pytest
from pydantic import ValidationError

from agent.messages import parse_alert_message

VALID_RAW = json.dumps(
    {
        "fingerprint": "abc123",
        "status": "firing",
        "alertname": "BoutiquePodCrashLooping",
        "labels": {"alertname": "BoutiquePodCrashLooping", "pod": "cartservice-abc"},
        "annotations": {"summary": "Pod is crash looping"},
        "starts_at": "2026-10-16T10:00:00Z",
        "ends_at": None,
    }
).encode("utf-8")


def test_parse_valid_message() -> None:
    message = parse_alert_message(VALID_RAW)
    assert message.fingerprint == "abc123"
    assert message.status == "firing"
    assert message.ends_at is None


def test_parse_invalid_json_raises() -> None:
    with pytest.raises(ValueError):
        parse_alert_message(b"not json")


def test_parse_missing_required_field_raises() -> None:
    bad = json.dumps({"fingerprint": "abc123"}).encode("utf-8")
    with pytest.raises(ValidationError):
        parse_alert_message(bad)
