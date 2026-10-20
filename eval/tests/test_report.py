import csv
from pathlib import Path
from typing import Any

from eval.report import summarize, write_csv
from eval.scoring import RunResult


def _result(**overrides: Any) -> RunResult:
    base: dict[str, Any] = dict(
        scenario="crash_loop", model="claude-haiku-5-5", repeat=0,
        root_cause_correct=True, root_cause_reason="matches",
        explanation_score=4, explanation_reason="clear",
        time_to_diagnosis_s=10.0, tool_calls=3,
        input_tokens=100, output_tokens=50, cost_usd="0.001",
        unsafe_action=False, status="complete",
    )
    base.update(overrides)
    return RunResult(**base)


def test_write_csv_writes_one_row_per_result(tmp_path: Path) -> None:
    path = tmp_path / "results.csv"
    write_csv([_result(), _result(repeat=1, root_cause_correct=False)], path)

    with path.open() as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 2
    assert rows[0]["scenario"] == "crash_loop"
    assert rows[1]["root_cause_correct"] == "False"


def test_summarize_groups_by_model_and_computes_accuracy() -> None:
    results = [
        _result(
            model="claude-haiku-5-5",
            scenario="crash_loop",
            repeat=0,
            root_cause_correct=True,
            time_to_diagnosis_s=10.0,
            cost_usd="0.001",
        ),
        _result(
            model="claude-haiku-5-5",
            scenario="crash_loop",
            repeat=1,
            root_cause_correct=True,
            time_to_diagnosis_s=20.0,
            cost_usd="0.002",
        ),
        _result(
            model="claude-haiku-5-5",
            scenario="oom",
            repeat=0,
            root_cause_correct=False,
            time_to_diagnosis_s=5.0,
            cost_usd="0.0005",
        ),
        _result(
            model="rule_based",
            scenario="crash_loop",
            repeat=0,
            root_cause_correct=False,
            time_to_diagnosis_s=1.0,
            cost_usd="0.0",
        ),
    ]
    table = summarize(results)
    assert "claude-haiku-5-5" in table
    assert "rule_based" in table
    assert "0.67" in table or "2/3" in table  # 2 of 3 haiku runs correct
