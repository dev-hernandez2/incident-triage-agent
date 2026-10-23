"""Shared approve/reject logic for a proposed remediation action.

No discord.py dependency here on purpose: this is the single place that
checks the approver role, transitions an Action's status, and writes the
audit_log row, so services/bot's buttons and services/dashboard's HTTP
endpoints both call exactly the same code path rather than each
reimplementing the safety rule.
"""

from datetime import UTC, datetime
from typing import Literal

from db.models import Action, AuditLog
from sqlalchemy.orm import Session

ApproveResult = Literal["approved", "rejected", "forbidden", "already_decided"]


def approve_action(
    session: Session, action: Action, approver_id: str, has_role: bool
) -> ApproveResult:
    if not has_role:
        return "forbidden"
    if action.status != "pending":
        return "already_decided"

    action.status = "approved"
    action.approved_by = approver_id
    action.approved_at = datetime.now(UTC)
    session.add(
        AuditLog(
            incident_id=action.incident_id,
            actor=f"bot:{approver_id}",
            event_type="approval",
            detail={"action_id": str(action.id), "type": action.type},
        )
    )
    session.flush()
    return "approved"


def reject_action(
    session: Session, action: Action, rejecter_id: str, reason: str, has_role: bool
) -> ApproveResult:
    if not has_role:
        return "forbidden"
    if action.status != "pending":
        return "already_decided"

    action.status = "rejected"
    action.rejection_reason = reason
    session.add(
        AuditLog(
            incident_id=action.incident_id,
            actor=f"bot:{rejecter_id}",
            event_type="rejection",
            detail={"action_id": str(action.id), "type": action.type, "reason": reason},
        )
    )
    session.flush()
    return "rejected"
