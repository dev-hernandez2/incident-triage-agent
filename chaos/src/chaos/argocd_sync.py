import time
from typing import Any

import httpx


class ArgoCdSyncTimeoutError(Exception):
    pass


class ArgoCdClient:
    def __init__(
        self,
        base_url: str,
        app_name: str,
        token: str,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.app_name = app_name
        self._http = http_client or httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
        )

    def _fetch_status(self) -> dict[str, str]:
        response = self._http.get(f"/api/v1/applications/{self.app_name}")
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        sync: dict[str, str] = data["status"]["sync"]
        return sync

    def current_sync_revision(self) -> str:
        return self._fetch_status()["revision"]

    def wait_for_sync(
        self,
        target_revision: str,
        *,
        timeout_s: float = 60,
        poll_interval_s: float = 2,
    ) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            status = self._fetch_status()
            if status["revision"] == target_revision and status["status"] == "Synced":
                return
            time.sleep(poll_interval_s)
        raise ArgoCdSyncTimeoutError(
            f"app {self.app_name!r} did not sync to revision {target_revision!r} "
            f"within {timeout_s}s"
        )
