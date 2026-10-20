"""Writes eval run results as a CSV and a Markdown accuracy/cost summary."""

import csv
import statistics
from pathlib import Path

from eval.scoring import RunResult

_FIELDS = list(RunResult.model_fields.keys())


def write_csv(results: list[RunResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDS)
        writer.writeheader()
        for result in results:
            writer.writerow(result.model_dump())


def summarize(results: list[RunResult]) -> str:
    by_model: dict[str, list[RunResult]] = {}
    for result in results:
        by_model.setdefault(result.model, []).append(result)

    lines = ["| model | accuracy | median_time_s | median_cost_usd | consistency | n_runs |",
             "|---|---|---|---|---|---|"]
    for model, rows in sorted(by_model.items()):
        accuracy = sum(r.root_cause_correct for r in rows) / len(rows)
        median_time = statistics.median(r.time_to_diagnosis_s for r in rows)
        median_cost = statistics.median(float(r.cost_usd) for r in rows)
        consistency = _consistency(rows)
        lines.append(
            f"| {model} | {accuracy:.2f} | {median_time:.1f} | {median_cost:.4f} | "
            f"{consistency:.2f} | {len(rows)} |"
        )
    return "\n".join(lines)


def _consistency(rows: list[RunResult]) -> float:
    by_scenario: dict[str, list[bool]] = {}
    for row in rows:
        by_scenario.setdefault(row.scenario, []).append(row.root_cause_correct)

    agreements = []
    for verdicts in by_scenario.values():
        if len(verdicts) < 2:
            continue
        majority = sum(verdicts) >= len(verdicts) / 2
        agreements.append(sum(1 for v in verdicts if v == majority) / len(verdicts))

    return sum(agreements) / len(agreements) if agreements else 1.0


def write_summary(results: list[RunResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(summarize(results) + "\n")
