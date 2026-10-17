"""Parses Kafka messages from the alerts.raw topic into a typed AlertMessage."""

import json

from pydantic import BaseModel


class AlertMessage(BaseModel):
    fingerprint: str
    status: str
    alertname: str
    labels: dict[str, str]
    annotations: dict[str, str]
    starts_at: str
    ends_at: str | None


def parse_alert_message(raw: bytes) -> AlertMessage:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in Kafka message: {exc}") from exc
    return AlertMessage.model_validate(data)
