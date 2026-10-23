"""Read endpoints for incidents/timeline/actions, plus approve/reject
write endpoints that share bot.actions' approve_action/reject_action so
there is exactly one place that enforces the approver-role rule.
"""

import uuid
from collections.abc import Callable

from bot.actions import approve_action, reject_action
from db.models import Action, AuditLog, Finding, Incident, ToolCall
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session


class RejectBody(BaseModel):
    reason: str


def create_app(
    session_factory: Callable[[], Session],
    role_checker: Callable[[str], bool],
    current_user_id: Callable[[Request], str] = lambda request: "dev-user",
) -> FastAPI:
    app = FastAPI()

    def get_session() -> Session:
        return session_factory()

    @app.get("/incidents")
    def list_incidents(session: Session = Depends(get_session)) -> list[dict[str, object]]:
        incidents = session.scalars(select(Incident).order_by(Incident.created_at.desc())).all()
        return [
            {"id": str(i.id), "alertname": i.alertname, "status": i.status}
            for i in incidents
        ]

    @app.get("/incidents/{incident_id}")
    def get_incident(
        incident_id: uuid.UUID, session: Session = Depends(get_session)
    ) -> dict[str, object]:
        incident = session.get(Incident, incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="incident not found")

        tool_calls = session.scalars(
            select(ToolCall).where(ToolCall.incident_id == incident_id)
        ).all()
        audit_entries = session.scalars(
            select(AuditLog).where(AuditLog.incident_id == incident_id)
        ).all()
        findings = session.scalars(
            select(Finding).where(Finding.incident_id == incident_id)
        ).all()

        timeline = sorted(
            [
                {
                    "created_at": tc.created_at.isoformat(),
                    "event_type": "tool_call",
                    "detail": tc.tool,
                }
                for tc in tool_calls
            ]
            + [
                {
                    "created_at": a.created_at.isoformat(),
                    "event_type": a.event_type,
                    "detail": a.detail,
                }
                for a in audit_entries
            ],
            key=lambda e: e["created_at"],  # type: ignore[arg-type, return-value]
        )

        return {
            "id": str(incident.id),
            "alertname": incident.alertname,
            "status": incident.status,
            "findings": [
                {
                    "id": str(f.id),
                    "summary": f.summary,
                    "root_cause": f.root_cause,
                    "evidence": f.evidence,
                    "suggested_fix": f.suggested_fix,
                }
                for f in findings
            ],
            "timeline": timeline,
        }

    @app.get("/incidents/{incident_id}/actions")
    def get_actions(
        incident_id: uuid.UUID, session: Session = Depends(get_session)
    ) -> list[dict[str, object]]:
        actions = session.scalars(
            select(Action).where(Action.incident_id == incident_id)
        ).all()
        return [
            {"id": str(a.id), "type": a.type, "status": a.status, "reason": a.reason}
            for a in actions
        ]

    @app.post("/actions/{action_id}/approve")
    def approve(
        action_id: uuid.UUID, request: Request, session: Session = Depends(get_session)
    ) -> dict[str, str]:
        action = session.get(Action, action_id)
        if action is None:
            raise HTTPException(status_code=404, detail="action not found")
        user_id = current_user_id(request)
        has_role = role_checker(user_id)
        result = approve_action(session, action, approver_id=user_id, has_role=has_role)
        if result == "forbidden":
            raise HTTPException(status_code=403, detail="you don't have the approver role")
        if result == "already_decided":
            raise HTTPException(status_code=409, detail="action already decided")
        return {"status": result}

    @app.post("/actions/{action_id}/reject")
    def reject(
        action_id: uuid.UUID,
        body: RejectBody,
        request: Request,
        session: Session = Depends(get_session),
    ) -> dict[str, str]:
        action = session.get(Action, action_id)
        if action is None:
            raise HTTPException(status_code=404, detail="action not found")
        user_id = current_user_id(request)
        has_role = role_checker(user_id)
        result = reject_action(
            session, action, rejecter_id=user_id, reason=body.reason, has_role=has_role
        )
        if result == "forbidden":
            raise HTTPException(status_code=403, detail="you don't have the approver role")
        if result == "already_decided":
            raise HTTPException(status_code=409, detail="action already decided")
        return {"status": result}

    return app
