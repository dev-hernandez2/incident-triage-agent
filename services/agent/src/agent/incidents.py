"""Idempotent incident creation/resolution against the incidents table."""

from db.models import Incident
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.messages import AlertMessage


def upsert_incident(session: Session, message: AlertMessage) -> Incident | None:
    if message.status == "firing":
        existing = session.scalar(
            select(Incident).where(
                Incident.fingerprint == message.fingerprint, Incident.status == "received"
            )
        )
        if existing is not None:
            return None
        incident = Incident(
            fingerprint=message.fingerprint,
            alertname=message.alertname,
            labels=message.labels,
            status="received",
        )
        session.add(incident)
        session.flush()
        return incident

    if message.status == "resolved":
        existing = session.scalar(
            select(Incident).where(
                Incident.fingerprint == message.fingerprint, Incident.status == "received"
            )
        )
        if existing is None:
            return None
        existing.status = "resolved"
        session.flush()
        return existing

    return None
