import json
from pathlib import Path

from eval.scenarios import SCENARIO_NAMES

_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def test_every_scenario_has_three_fixture_runs() -> None:
    for scenario in SCENARIO_NAMES:
        for repeat in range(3):
            path = _FIXTURES_DIR / scenario / f"run-{repeat}.json"
            assert path.exists(), f"missing fixture {path}"


def test_every_fixture_entry_matches_the_recorded_schema() -> None:
    for scenario in SCENARIO_NAMES:
        for repeat in range(3):
            path = _FIXTURES_DIR / scenario / f"run-{repeat}.json"
            entries = json.loads(path.read_text())
            assert isinstance(entries, list)
            assert len(entries) >= 1
            for i, entry in enumerate(entries):
                assert entry["index"] == i
                assert isinstance(entry["tool"], str)
                assert isinstance(entry["args"], dict)
                assert isinstance(entry["output"], str)
