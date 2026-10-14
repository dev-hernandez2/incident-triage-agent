import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class StateCorruptError(Exception):
    pass


@dataclass
class ActiveInjection:
    scenario: str
    service: str
    namespace: str
    injected_at: str
    saved_state: dict[str, Any]


_REQUIRED_FIELDS = {"scenario", "service", "namespace", "injected_at", "saved_state"}


class StateStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> ActiveInjection | None:
        if not self._path.exists():
            return None
        try:
            raw = json.loads(self._path.read_text())
        except json.JSONDecodeError as exc:
            raise StateCorruptError(f"{self._path} is not valid JSON") from exc
        if not isinstance(raw, dict) or not _REQUIRED_FIELDS.issubset(raw.keys()):
            raise StateCorruptError(f"{self._path} is missing required fields")
        return ActiveInjection(**raw)

    def save(self, injection: ActiveInjection) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(asdict(injection), indent=2))

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)
