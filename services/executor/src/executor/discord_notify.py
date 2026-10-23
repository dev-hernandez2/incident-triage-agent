"""Posts an executor outcome to Discord via an incoming webhook URL — a
one-way notification, so the executor doesn't need a full gateway client
the way services/bot does."""

import httpx


def post_outcome(webhook_url: str, incident_id: str, action_type: str, outcome: str) -> None:
    httpx.post(
        webhook_url,
        json={"content": f"Incident `{incident_id}`: {action_type} action — {outcome}"},
        timeout=10.0,
    )
