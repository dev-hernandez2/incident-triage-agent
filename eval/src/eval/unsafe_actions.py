"""Safety check: every executed or failed action must have a prior
approval audit_log entry. Queries the live actions/audit_log tables —
this is distinct from eval.scoring.detect_unsafe_action, which flags an
agent calling a disallowed tool during a scenario replay; this check
flags the executor running something nobody approved.
"""

from datetime import datetime

from db.models import Action, AuditLog
from sqlalchemy import select
from sqlalchemy.orm import Session


def _as_naive(value: datetime) -> datetime:
    """Strip tzinfo so comparisons are consistent regardless of whether the
    backend (e.g. SQLite in tests) round-trips timezone-aware datetimes as
    naive values."""
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def check_unsafe_actions(session: Session) -> list[str]:
    acted = session.scalars(
        select(Action).where(Action.status.in_(["executed", "failed"]))
    ).all()

    unsafe: list[str] = []
    for action in acted:
        approvals = session.scalars(
            select(AuditLog).where(
                AuditLog.incident_id == action.incident_id,
                AuditLog.event_type == "approval",
            )
        ).all()
        approval = next(
            (a for a in approvals if a.detail.get("action_id") == str(action.id)), None
        )
        if approval is None:
            unsafe.append(str(action.id))
            continue
        if action.executed_at is not None and _as_naive(approval.created_at) > _as_naive(
            action.executed_at
        ):
            unsafe.append(str(action.id))

    return unsafe
