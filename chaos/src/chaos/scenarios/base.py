from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import yaml

_DEFINITIONS_DIR = Path(__file__).parent / "definitions"


@dataclass
class ScenarioDefinition:
    name: str
    description: str
    root_cause_label: str
    expected_fix: str
    fixed_service: str | None
    default_params: dict[str, Any]
    injected_instruction: str | None = None


def load_definition(name: str) -> ScenarioDefinition:
    path = _DEFINITIONS_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no scenario definition for {name!r} at {path}")
    raw = yaml.safe_load(path.read_text())
    return ScenarioDefinition(**raw)


class Scenario(ABC):
    name: ClassVar[str]
    requires_service: ClassVar[bool]

    @abstractmethod
    def inject(self, k8s: Any, service: str) -> dict[str, Any]:
        """Apply the fault, return a JSON-serializable snapshot for revert()."""

    @abstractmethod
    def revert(self, k8s: Any, service: str, saved_state: dict[str, Any]) -> None:
        """Restore exactly what inject() overwrote."""

    def ground_truth(self, service: str) -> dict[str, Any]:
        definition = load_definition(self.name)
        affected_service = definition.fixed_service or service
        return {
            "root_cause_label": definition.root_cause_label,
            "affected_service": affected_service,
            "expected_fix": definition.expected_fix,
        }
