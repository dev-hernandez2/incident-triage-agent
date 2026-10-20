"""Typer CLI: `uv run --package triage-eval eval [options]`."""

import os
import subprocess
import time
from decimal import Decimal
from pathlib import Path
from typing import Annotated

import httpx
import typer

from eval.report import write_csv, write_summary
from eval.runner import RunnerConfig, run_all
from eval.scenarios import SCENARIO_NAMES
from eval.scoring import RunResult

app = typer.Typer()


def _chaos_inject(scenario: str) -> None:
    subprocess.run(["chaos", "inject", scenario], check=True)


def _chaos_revert() -> None:
    subprocess.run(["chaos", "revert"], check=True)


def _poll_alert_firing(alertname: str, timeout_s: float) -> dict[str, object] | None:
    prometheus_url = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        response = httpx.get(f"{prometheus_url}/api/v1/alerts", timeout=10.0)
        response.raise_for_status()
        for alert in response.json().get("data", {}).get("alerts", []):
            alert_name = alert.get("labels", {}).get("alertname")
            alert_state = alert.get("state")
            if alert_name == alertname and alert_state == "firing":
                return {
                    "alertname": alertname,
                    "labels": alert.get("labels", {}),
                    "annotations": alert.get("annotations", {}),
                }
        time.sleep(5)
    raise TimeoutError(f"alert {alertname!r} did not fire within {timeout_s}s")


def _poll_cluster_healthy() -> None:
    from chaos.k8s import K8sClient

    client = K8sClient(namespace="boutique")
    for service in (
        "adservice", "cartservice", "checkoutservice", "currencyservice", "emailservice",
        "frontend", "loadgenerator", "paymentservice", "productcatalogservice",
        "recommendationservice", "redis-cart", "shippingservice",
    ):
        client.wait_for_container_ready(f"app={service}", service, timeout_seconds=120)


def _accuracy_regressed(baseline_path: Path, results: list[RunResult]) -> bool:
    assert all(isinstance(r, RunResult) for r in results)
    if not results:
        return False

    baseline_text = baseline_path.read_text()
    baseline_accuracy = None
    for line in baseline_text.splitlines():
        if line.startswith("| ci-smoke-baseline"):
            baseline_accuracy = float(line.split("|")[2].strip())
            break
    if baseline_accuracy is None:
        return False

    current_accuracy = sum(r.root_cause_correct for r in results) / len(results)
    return current_accuracy < baseline_accuracy


@app.command()
def main(
    replay: Annotated[bool, typer.Option("--replay")] = False,
    models: Annotated[str, typer.Option("--models")] = "claude-haiku-5-5",
    scenarios: Annotated[str, typer.Option("--scenarios")] = ",".join(SCENARIO_NAMES),
    repeats: Annotated[int, typer.Option("--repeats")] = 5,
    fixtures: Annotated[Path, typer.Option("--fixtures")] = Path("eval/fixtures"),
    budget: Annotated[float | None, typer.Option("--budget")] = None,
) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    budget_usd = Decimal(str(budget)) if budget is not None else Decimal(
        os.environ.get("EVAL_BUDGET_USD", "20")
    )
    database_url = os.environ.get("DATABASE_URL", "postgresql://triage:triage@localhost:5432/triage")
    engine = create_engine(database_url)

    config = RunnerConfig(
        models=models.split(","),
        scenarios=scenarios.split(","),
        repeats=repeats,
        replay=replay,
        fixtures_dir=fixtures,
        budget_usd=budget_usd,
    )

    results = run_all(
        config,
        session_factory=lambda: Session(engine),
        chaos_inject=_chaos_inject,
        chaos_revert=_chaos_revert,
        poll_alert_firing=_poll_alert_firing,
        poll_cluster_healthy=_poll_cluster_healthy,
    )

    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    results_dir = Path("eval/results")
    write_csv(results, results_dir / f"{timestamp}.csv")
    write_summary(results, results_dir / f"{timestamp}_summary.md")

    accuracy = sum(r.root_cause_correct for r in results) / len(results) if results else 0.0
    typer.echo(f"{len(results)} runs complete. Accuracy: {accuracy:.2%}")

    baseline_path = results_dir / "latest_summary.md"
    if baseline_path.exists():
        if _accuracy_regressed(baseline_path, results):
            typer.echo("accuracy regressed vs. eval/results/latest_summary.md")
            raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
