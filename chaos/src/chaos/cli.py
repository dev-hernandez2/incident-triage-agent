from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

import typer

from chaos.scenarios.bad_deploy import BadDeployScenario
from chaos.scenarios.base import Scenario, load_definition
from chaos.scenarios.cpu_throttle import CpuThrottleScenario
from chaos.scenarios.crash_loop import CrashLoopScenario
from chaos.scenarios.oom import OomScenario
from chaos.scenarios.slow_redis import SlowRedisScenario
from chaos.state import ActiveInjection, StateCorruptError, StateStore

app = typer.Typer()

NAMESPACE = "boutique"

SERVICES = [
    "adservice",
    "cartservice",
    "checkoutservice",
    "currencyservice",
    "emailservice",
    "frontend",
    "loadgenerator",
    "paymentservice",
    "productcatalogservice",
    "recommendationservice",
    "redis-cart",
    "shippingservice",
]

_SCENARIOS: dict[str, type[Scenario]] = {
    "crash_loop": CrashLoopScenario,
    "oom": OomScenario,
    "bad_deploy": BadDeployScenario,
    "cpu_throttle": CpuThrottleScenario,
    "slow_redis": SlowRedisScenario,
}


def _state_path() -> Path:
    # Anchored to the chaos package's own location rather than the caller's
    # cwd, so the single-active-injection invariant holds no matter which
    # directory `chaos` is invoked from.
    return Path(__file__).resolve().parents[2] / ".state" / "active.json"


def _build_k8s_client() -> Any:
    from chaos.k8s import K8sClient

    return K8sClient(namespace=NAMESPACE)


def _fail(message: str) -> NoReturn:
    typer.echo(message)
    raise typer.Exit(code=1)


def _resolve_scenario(name: str) -> type[Scenario]:
    scenario_cls = _SCENARIOS.get(name)
    if scenario_cls is None:
        _fail(f"unknown scenario {name!r}. Valid scenarios: {', '.join(sorted(_SCENARIOS))}")
    return scenario_cls


@app.command("list")
def list_scenarios() -> None:
    for name in sorted(_SCENARIOS):
        definition = load_definition(name)
        scenario_cls = _SCENARIOS[name]
        suffix = " (requires --service)" if scenario_cls.requires_service else ""
        typer.echo(f"{name}: {definition.description}{suffix}")


@app.command("inject")
def inject(
    scenario: str,
    service: str = typer.Option(None, "--service"),
) -> None:
    store = StateStore(_state_path())
    try:
        active = store.load()
    except StateCorruptError as exc:
        _fail(f"state file is corrupt: {exc}")

    if active is not None:
        _fail(
            f"scenario {active.scenario!r} is already active on {active.service!r}. "
            "Run `chaos revert` first."
        )

    scenario_cls = _resolve_scenario(scenario)
    scenario_instance = scenario_cls()

    if scenario_instance.requires_service:
        if service is None:
            _fail(
                f"scenario {scenario!r} requires --service. Valid services: {', '.join(SERVICES)}"
            )
        if service not in SERVICES:
            _fail(f"unknown service {service!r}. Valid services: {', '.join(SERVICES)}")
        target_service = service
    else:
        definition = load_definition(scenario)
        if service is not None and service != definition.fixed_service:
            _fail(
                f"scenario {scenario!r} has a fixed target "
                f"({definition.fixed_service!r}); --service may not be overridden"
            )
        target_service = definition.fixed_service or ""

    # Record a placeholder before touching the cluster: if inject() raises
    # partway through, or the real save below fails, `chaos status` still
    # shows an active injection (with no snapshot yet) rather than silently
    # losing all record that the cluster may have been mutated.
    pending = ActiveInjection(
        scenario=scenario,
        service=target_service,
        namespace=NAMESPACE,
        injected_at=datetime.now(UTC).isoformat(),
        saved_state={},
    )
    store.save(pending)

    k8s = _build_k8s_client()
    saved_state = scenario_instance.inject(k8s, target_service)

    store.save(
        ActiveInjection(
            scenario=scenario,
            service=target_service,
            namespace=NAMESPACE,
            injected_at=pending.injected_at,
            saved_state=saved_state,
        )
    )

    ground_truth = scenario_instance.ground_truth(target_service)
    typer.echo(f"injected {scenario!r} on {target_service!r}")
    typer.echo(f"ground truth: {ground_truth}")


@app.command("revert")
def revert(scenario: str = typer.Argument(None)) -> None:
    store = StateStore(_state_path())
    try:
        active = store.load()
    except StateCorruptError as exc:
        _fail(f"state file is corrupt: {exc}")

    if active is None:
        _fail("no active injection to revert")

    if scenario is not None and scenario != active.scenario:
        _fail(f"active injection is {active.scenario!r}, not {scenario!r}")

    scenario_cls = _resolve_scenario(active.scenario)
    scenario_instance = scenario_cls()

    k8s = _build_k8s_client()
    scenario_instance.revert(k8s, active.service, active.saved_state)

    store.clear()
    typer.echo(f"reverted {active.scenario!r} on {active.service!r}")


@app.command("status")
def status() -> None:
    store = StateStore(_state_path())
    try:
        active = store.load()
    except StateCorruptError as exc:
        _fail(f"state file is corrupt: {exc}")

    if active is None:
        typer.echo("no active injection")
        return

    typer.echo(
        f"active: scenario={active.scenario} service={active.service} "
        f"injected_at={active.injected_at}"
    )


if __name__ == "__main__":
    app()
