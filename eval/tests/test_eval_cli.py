"""Tests for the eval CLI's accuracy-regression gate."""

from pathlib import Path

from eval.cli import _accuracy_regressed
from eval.scoring import RunResult


def _result(correct: bool) -> RunResult:
    return RunResult(
        scenario="crash_loop",
        model="claude-haiku-5-5",
        repeat=0,
        root_cause_correct=correct,
        root_cause_reason="",
        explanation_score=0,
        explanation_reason="",
        time_to_diagnosis_s=1.0,
        tool_calls=1,
        input_tokens=1,
        output_tokens=1,
        cost_usd="0.01",
        unsafe_action=False,
        status="complete",
    )


def _write_baseline(path: Path, accuracy: float) -> Path:
    baseline_path = path / "latest_summary.md"
    baseline_path.write_text(
        "| model | accuracy | median_time_s | median_cost_usd | consistency | n_runs |\n"
        "|---|---|---|---|---|---|\n"
        f"| ci-smoke-baseline | {accuracy} | 12.4 | 0.0294 | 0.78 | 9 |\n"
    )
    return baseline_path


def test_small_drop_within_tolerance_is_not_a_regression(tmp_path: Path) -> None:
    baseline_path = _write_baseline(tmp_path, 0.50)
    # 4/9 correct = 44.4%, within the 20-point tolerance band of a 50% baseline.
    results = [_result(True)] * 4 + [_result(False)] * 5
    assert not _accuracy_regressed(baseline_path, results)


def test_large_drop_beyond_tolerance_is_a_regression(tmp_path: Path) -> None:
    baseline_path = _write_baseline(tmp_path, 0.50)
    # 0/9 correct = 0%, well beyond the 20-point tolerance band.
    results = [_result(False)] * 9
    assert _accuracy_regressed(baseline_path, results)


def test_no_results_is_not_a_regression(tmp_path: Path) -> None:
    baseline_path = _write_baseline(tmp_path, 0.50)
    assert not _accuracy_regressed(baseline_path, [])


def test_missing_baseline_row_is_not_a_regression(tmp_path: Path) -> None:
    baseline_path = tmp_path / "latest_summary.md"
    baseline_path.write_text("| model | accuracy |\n|---|---|\n")
    assert not _accuracy_regressed(baseline_path, [_result(False)])
