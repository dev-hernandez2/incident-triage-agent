"""Persists a validated Findings object and its cost into the findings table."""

from decimal import Decimal

from db.models import Finding, Incident
from llm.types import Usage
from sqlalchemy.orm import Session

from agent.findings import Findings


def save_finding(
    session: Session, incident: Incident, findings: Findings, usage: Usage, cost_usd: Decimal
) -> Finding:
    row = Finding(
        incident_id=incident.id,
        summary=findings.summary,
        root_cause=findings.root_cause,
        confidence=findings.confidence,
        evidence=[e.model_dump() for e in findings.evidence],
        affected_services=findings.affected_services,
        suggested_fix=findings.suggested_fix.model_dump(),
        ruled_out=findings.ruled_out,
        status=findings.status,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=cost_usd,
    )
    session.add(row)
    session.flush()
    return row
