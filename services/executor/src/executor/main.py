"""The only service permitted to mutate cluster state.

Polls the actions table for approved remediation actions, executes them
against a namespace-scoped Kubernetes client, watches for up to 5 minutes
for the triggering incident to resolve, and posts the outcome to Discord.
Never invoked directly by services/agent — see deploy/k8s/rbac-triage-executor.yaml
for the ServiceAccount this runs as.
"""

import logging
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from db.models import Action, AuditLog, Incident
from sqlalchemy import CursorResult, create_engine, select, update
from sqlalchemy.orm import Session

from executor.discord_notify import post_outcome
from executor.k8s_client import K8sExecutorClient

POLL_INTERVAL_SECONDS = 5.0
RECOVERY_TIMEOUT_SECONDS = 300.0
RECOVERY_POLL_INTERVAL_SECONDS = 10.0

logger = logging.getLogger(__name__)


class K8sExecutorClientProtocol(Protocol):
    def restart(self, deployment: str) -> None: ...
    def scale(self, deployment: str, replicas: int) -> None: ...
    def rollback(self, deployment: str) -> None: ...


def claim_approved_action(session: Session) -> Action | None:
    """Atomically claim the oldest approved action.

    Uses a single conditional UPDATE (WHERE status = 'approved') rather than
    a SELECT followed by a separate write, so two concurrent poll cycles —
    even on separate Postgres connections — can never both claim the same
    row: only one UPDATE can match a given row while its status is still
    'approved', because the second UPDATE's WHERE clause no longer matches
    once the first has (logically) changed it. The candidate id is chosen
    first via a plain SELECT so this remains a single-row update instead of
    claiming every approved action in the table at once.
    """
    candidate_id = session.scalar(
        select(Action.id).where(Action.status == "approved").order_by(Action.created_at).limit(1)
    )
    if candidate_id is None:
        return None

    result = cast(
        "CursorResult[Any]",
        session.execute(
            update(Action)
            .where(Action.id == candidate_id, Action.status == "approved")
            .values(status="executing")
        ),
    )
    session.flush()
    if result.rowcount == 0:
        # Another poller claimed it between our SELECT and our UPDATE.
        return None

    action = session.get(Action, candidate_id)
    if action is not None:
        session.refresh(action)
    return action


def execute_action(session: Session, action: Action, k8s_client: K8sExecutorClientProtocol) -> None:
    if action.type == "manual":
        action.status = "failed"
        action.outcome = "refused: manual actions are never executed"
        session.add(
            AuditLog(
                incident_id=action.incident_id,
                actor="executor",
                event_type="action_failed",
                detail={"action_id": str(action.id), "type": action.type},
            )
        )
        session.flush()
        return

    assert action.deployment is not None
    if action.type == "rollback":
        k8s_client.rollback(action.deployment)
    elif action.type == "restart":
        k8s_client.restart(action.deployment)
    elif action.type == "scale":
        assert action.replicas is not None
        k8s_client.scale(action.deployment, action.replicas)

    action.executed_at = datetime.now(UTC)
    session.add(
        AuditLog(
            incident_id=action.incident_id,
            actor="executor",
            event_type="action_executed",
            detail={"action_id": str(action.id), "type": action.type},
        )
    )
    session.flush()


def poll_for_recovery(
    session: Session,
    action: Action,
    timeout_seconds: float,
    poll_interval_seconds: float,
    sleep: Callable[[float], None],
    now: Callable[[], datetime],
) -> bool:
    deadline = now().timestamp() + timeout_seconds
    while now().timestamp() < deadline:
        sleep(poll_interval_seconds)
        incident = session.get(Incident, action.incident_id)
        if incident is not None and incident.status == "resolved":
            return True
    return False


def _finalize(session: Session, action: Action, resolved: bool) -> None:
    action.status = "executed" if resolved else "failed"
    action.outcome = "resolved" if resolved else "timed out after 5m"
    session.add(
        AuditLog(
            incident_id=action.incident_id,
            actor="executor",
            event_type="action_executed" if resolved else "action_failed",
            detail={"action_id": str(action.id), "outcome": action.outcome},
        )
    )
    session.flush()


def run_once(session: Session, k8s_client: K8sExecutorClientProtocol, webhook_url: str) -> None:
    action = claim_approved_action(session)
    if action is None:
        return
    session.commit()

    execute_action(session, action, k8s_client)
    session.commit()

    if action.status == "failed":
        post_outcome(webhook_url, str(action.incident_id), action.type, action.outcome or "failed")
        return

    resolved = poll_for_recovery(
        session,
        action,
        timeout_seconds=RECOVERY_TIMEOUT_SECONDS,
        poll_interval_seconds=RECOVERY_POLL_INTERVAL_SECONDS,
        sleep=time.sleep,
        now=lambda: datetime.now(UTC),
    )
    _finalize(session, action, resolved)
    session.commit()

    post_outcome(webhook_url, str(action.incident_id), action.type, action.outcome or "")


def main() -> None:
    database_url = os.environ.get(
        "DATABASE_URL", "postgresql://triage:triage@localhost:5432/triage"
    )
    webhook_url = os.environ["DISCORD_WEBHOOK_URL"]
    namespace = os.environ.get("EXECUTOR_NAMESPACE", "boutique")

    engine = create_engine(database_url)
    k8s_client = K8sExecutorClient(allowed_namespace=namespace)

    while True:
        session = Session(engine)
        try:
            run_once(session, k8s_client, webhook_url)
        except Exception:
            session.rollback()
            logger.exception("executor loop iteration failed")
        finally:
            session.close()
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
