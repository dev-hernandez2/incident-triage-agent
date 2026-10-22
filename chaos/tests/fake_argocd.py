from typing import Any

import httpx


class FakeArgoCdTransport(httpx.BaseTransport):
    """Stands in for the real Argo CD REST API in tests."""

    def __init__(self) -> None:
        self.synced_revision = "0" * 40
        self.sync_status = "Synced"
        # Call set_synced_revision from a test to simulate Argo CD catching
        # up to a newly pushed commit mid-poll.
        self._poll_count = 0
        self.synced_after_polls: int | None = None
        self.pending_revision: str | None = None

    def set_synced_after(self, revision: str, polls: int) -> None:
        """Simulate Argo CD syncing `revision` after `polls` status checks."""
        self.pending_revision = revision
        self.synced_after_polls = polls
        self._poll_count = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/sync-status")
        if self.synced_after_polls is not None:
            self._poll_count += 1
            if self._poll_count >= self.synced_after_polls:
                self.synced_revision = self.pending_revision or self.synced_revision
                self.sync_status = "Synced"
            else:
                self.sync_status = "Progressing"
        body: dict[str, Any] = {
            "revision": self.synced_revision,
            "status": self.sync_status,
        }
        return httpx.Response(200, json=body)
