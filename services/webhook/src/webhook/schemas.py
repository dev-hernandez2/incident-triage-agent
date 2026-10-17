"""Pydantic models for Alertmanager's webhook payload and the internal Kafka message schema."""

from pydantic import BaseModel


class AlertmanagerAlert(BaseModel):
    status: str
    labels: dict[str, str]
    annotations: dict[str, str]
    startsAt: str
    endsAt: str
    fingerprint: str


class AlertmanagerWebhookPayload(BaseModel):
    version: str
    groupKey: str
    status: str
    receiver: str
    alerts: list[AlertmanagerAlert]


class AlertMessage(BaseModel):
    fingerprint: str
    status: str
    alertname: str
    labels: dict[str, str]
    annotations: dict[str, str]
    starts_at: str
    ends_at: str | None


_RESOLVED_SENTINEL_END = "0001-01-01T00:00:00Z"


def to_alert_message(alert: AlertmanagerAlert) -> AlertMessage:
    return AlertMessage(
        fingerprint=alert.fingerprint,
        status=alert.status,
        alertname=alert.labels.get("alertname", "unknown"),
        labels=alert.labels,
        annotations=alert.annotations,
        starts_at=alert.startsAt,
        ends_at=None if alert.endsAt == _RESOLVED_SENTINEL_END else alert.endsAt,
    )
