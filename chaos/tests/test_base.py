from pathlib import Path

import pytest
import yaml

from chaos.scenarios.base import Scenario, ScenarioDefinition, load_definition


def test_load_definition_reads_yaml(tmp_path, monkeypatch):
    definitions_dir = tmp_path / "definitions"
    definitions_dir.mkdir()
    (definitions_dir / "dummy.yaml").write_text(
        yaml.dump(
            {
                "name": "dummy",
                "description": "A dummy scenario",
                "root_cause_label": "dummy cause",
                "expected_fix": "dummy fix",
                "fixed_service": None,
                "default_params": {"x": 1},
            }
        )
    )
    monkeypatch.setattr(
        "chaos.scenarios.base._DEFINITIONS_DIR", definitions_dir
    )

    definition = load_definition("dummy")

    assert definition == ScenarioDefinition(
        name="dummy",
        description="A dummy scenario",
        root_cause_label="dummy cause",
        expected_fix="dummy fix",
        fixed_service=None,
        default_params={"x": 1},
    )


def test_load_definition_missing_file_raises(tmp_path, monkeypatch):
    monkeypatch.setattr("chaos.scenarios.base._DEFINITIONS_DIR", tmp_path)
    with pytest.raises(FileNotFoundError):
        load_definition("does-not-exist")


class _DummyScenario(Scenario):
    name = "dummy"
    requires_service = True

    def inject(self, k8s, service):
        return {}

    def revert(self, k8s, service, saved_state):
        pass


def test_ground_truth_uses_passed_service_when_no_fixed_service(tmp_path, monkeypatch):
    definitions_dir = tmp_path / "definitions"
    definitions_dir.mkdir()
    (definitions_dir / "dummy.yaml").write_text(
        yaml.dump(
            {
                "name": "dummy",
                "description": "d",
                "root_cause_label": "cause",
                "expected_fix": "fix",
                "fixed_service": None,
                "default_params": {},
            }
        )
    )
    monkeypatch.setattr("chaos.scenarios.base._DEFINITIONS_DIR", definitions_dir)

    gt = _DummyScenario().ground_truth("cartservice")

    assert gt == {
        "root_cause_label": "cause",
        "affected_service": "cartservice",
        "expected_fix": "fix",
    }


def test_ground_truth_uses_fixed_service_when_set(tmp_path, monkeypatch):
    definitions_dir = tmp_path / "definitions"
    definitions_dir.mkdir()
    (definitions_dir / "dummy.yaml").write_text(
        yaml.dump(
            {
                "name": "dummy",
                "description": "d",
                "root_cause_label": "cause",
                "expected_fix": "fix",
                "fixed_service": "paymentservice",
                "default_params": {},
            }
        )
    )
    monkeypatch.setattr("chaos.scenarios.base._DEFINITIONS_DIR", definitions_dir)

    gt = _DummyScenario().ground_truth("anything-ignored")

    assert gt["affected_service"] == "paymentservice"
