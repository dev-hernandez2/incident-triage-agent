from pathlib import Path
from typing import Any
from unittest.mock import patch

from boutique_manifest import real_containers
from chaos.cli import SERVICES, app
from chaos.state import StateStore
from fake_k8s import FakeK8sClient
from typer.testing import CliRunner

runner = CliRunner()


def _state_path(tmp_path: Path) -> Path:
    return tmp_path / "active.json"


def _patched(tmp_path: Path, fake: FakeK8sClient) -> tuple[Any, Any]:
    return (
        patch("chaos.cli._state_path", return_value=_state_path(tmp_path)),
        patch("chaos.cli._build_k8s_client", return_value=fake),
    )


def _seed_paymentservice(fake: FakeK8sClient) -> None:
    fake.seed_deployment("paymentservice", real_containers("paymentservice"))


def test_list_shows_all_five_scenarios() -> None:
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    for name in ["crash_loop", "oom", "bad_deploy", "cpu_throttle", "slow_redis"]:
        assert name in result.stdout


def test_list_shows_which_scenarios_require_service() -> None:
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    lines = {line.split(":")[0]: line for line in result.stdout.splitlines()}
    # scenarios that require --service say so on their own line
    for name in ["oom", "bad_deploy", "cpu_throttle"]:
        assert "--service" in lines[name]
    # fixed-target scenarios don't need --service
    for name in ["crash_loop", "slow_redis"]:
        assert "--service" not in lines[name]


def test_inject_requires_service_for_scenarios_that_need_one(tmp_path: Path) -> None:
    fake = FakeK8sClient()
    p1, p2 = _patched(tmp_path, fake)
    with p1, p2:
        result = runner.invoke(app, ["inject", "oom"])
    assert result.exit_code != 0
    assert "--service" in result.stdout
    for name in SERVICES:
        assert name in result.stdout


def test_inject_rejects_service_for_fixed_target_scenario(tmp_path: Path) -> None:
    fake = FakeK8sClient()
    p1, p2 = _patched(tmp_path, fake)
    with p1, p2:
        result = runner.invoke(app, ["inject", "crash_loop", "--service", "frontend"])
    assert result.exit_code != 0
    assert "paymentservice" in result.stdout


def test_inject_happy_path_writes_state(tmp_path: Path) -> None:
    fake = FakeK8sClient()
    _seed_paymentservice(fake)
    p1, p2 = _patched(tmp_path, fake)
    with p1, p2:
        result = runner.invoke(app, ["inject", "crash_loop"])

    assert result.exit_code == 0
    store = StateStore(_state_path(tmp_path))
    active = store.load()
    assert active is not None
    assert active.scenario == "crash_loop"
    assert active.service == "paymentservice"


def test_inject_refuses_when_already_active(tmp_path: Path) -> None:
    fake = FakeK8sClient()
    _seed_paymentservice(fake)
    p1, p2 = _patched(tmp_path, fake)
    with p1, p2:
        runner.invoke(app, ["inject", "crash_loop"])
        result = runner.invoke(app, ["inject", "crash_loop"])

    assert result.exit_code != 0
    assert "already active" in result.stdout.lower()


def test_inject_rejects_unknown_scenario(tmp_path: Path) -> None:
    fake = FakeK8sClient()
    p1, p2 = _patched(tmp_path, fake)
    with p1, p2:
        result = runner.invoke(app, ["inject", "not-a-real-scenario"])
    assert result.exit_code != 0
    assert "crash_loop" in result.stdout


def test_inject_rejects_unknown_service(tmp_path: Path) -> None:
    fake = FakeK8sClient()
    p1, p2 = _patched(tmp_path, fake)
    with p1, p2:
        result = runner.invoke(app, ["inject", "oom", "--service", "not-a-real-service"])
    assert result.exit_code != 0
    assert "frontend" in result.stdout  # one of the valid names is listed


def test_revert_restores_and_clears_state(tmp_path: Path) -> None:
    fake = FakeK8sClient()
    _seed_paymentservice(fake)
    p1, p2 = _patched(tmp_path, fake)
    with p1, p2:
        runner.invoke(app, ["inject", "crash_loop"])
        result = runner.invoke(app, ["revert"])

    assert result.exit_code == 0
    reverted = fake.deployments["paymentservice"]["containers"][0]
    assert reverted == real_containers("paymentservice")[0]
    store = StateStore(_state_path(tmp_path))
    assert store.load() is None


def test_revert_errors_when_nothing_active(tmp_path: Path) -> None:
    fake = FakeK8sClient()
    p1, p2 = _patched(tmp_path, fake)
    with p1, p2:
        result = runner.invoke(app, ["revert"])
    assert result.exit_code != 0
    assert "no active injection" in result.stdout.lower()


def test_revert_errors_when_scenario_arg_mismatches_active(tmp_path: Path) -> None:
    fake = FakeK8sClient()
    _seed_paymentservice(fake)
    p1, p2 = _patched(tmp_path, fake)
    with p1, p2:
        runner.invoke(app, ["inject", "crash_loop"])
        result = runner.invoke(app, ["revert", "oom"])

    assert result.exit_code != 0
    assert "crash_loop" in result.stdout


def test_status_reports_none_then_active(tmp_path: Path) -> None:
    fake = FakeK8sClient()
    _seed_paymentservice(fake)
    p1, p2 = _patched(tmp_path, fake)
    with p1, p2:
        empty_result = runner.invoke(app, ["status"])
        runner.invoke(app, ["inject", "crash_loop"])
        active_result = runner.invoke(app, ["status"])

    assert "no active injection" in empty_result.stdout.lower()
    assert "crash_loop" in active_result.stdout
    assert "paymentservice" in active_result.stdout


def test_status_errors_clearly_on_corrupt_state_file(tmp_path: Path) -> None:
    path = _state_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json")
    fake = FakeK8sClient()
    p1, p2 = _patched(tmp_path, fake)
    with p1, p2:
        result = runner.invoke(app, ["status"])
    assert result.exit_code != 0
    assert "corrupt" in result.stdout.lower()


def test_default_state_path_is_not_relative_to_the_current_working_directory() -> None:
    import chaos.cli as cli_module

    path = cli_module._state_path()
    # a relative Path("chaos/.state/active.json") resolves differently
    # depending on the caller's cwd, which breaks the single-active-injection
    # invariant if chaos is invoked from different directories
    assert path.is_absolute()


def test_inject_bad_deploy_refuses_when_another_scenario_active(tmp_path: Path) -> None:
    fake = FakeK8sClient()
    _seed_paymentservice(fake)
    p1, p2 = _patched(tmp_path, fake)
    with (
        p1,
        p2,
        patch("chaos.cli._build_boutique_deploy_repo") as repo_factory,
        patch("chaos.cli._build_argocd_client") as argocd_factory,
    ):
        runner.invoke(app, ["inject", "crash_loop"])
        result = runner.invoke(app, ["inject", "bad_deploy", "--service", "frontend"])

    assert result.exit_code != 0
    assert "already active" in result.stdout.lower()
    repo_factory.assert_not_called()
    argocd_factory.assert_not_called()


def test_revert_errors_when_nothing_active_for_bad_deploy(tmp_path: Path) -> None:
    fake = FakeK8sClient()
    p1, p2 = _patched(tmp_path, fake)
    with (
        p1,
        p2,
        patch("chaos.cli._build_boutique_deploy_repo") as repo_factory,
        patch("chaos.cli._build_argocd_client") as argocd_factory,
    ):
        result = runner.invoke(app, ["revert", "bad_deploy"])
    assert result.exit_code != 0
    assert "no active injection" in result.stdout.lower()
    repo_factory.assert_not_called()
    argocd_factory.assert_not_called()


def test_inject_records_state_before_mutating_the_cluster(tmp_path: Path) -> None:
    """If inject() succeeds against the cluster but persisting state then
    fails, the CLI must not leave the cluster mutated with no record of
    it (the ground truth / undo snapshot would be lost)."""
    fake = FakeK8sClient()
    _seed_paymentservice(fake)
    p1, p2 = _patched(tmp_path, fake)
    with p1, p2, patch("chaos.cli.StateStore.save", side_effect=OSError("disk full")):
        result = runner.invoke(app, ["inject", "crash_loop"])

    assert result.exit_code != 0
    # the cluster must not have been mutated if the state couldn't be recorded
    unmutated = fake.deployments["paymentservice"]["containers"][0]
    assert unmutated == real_containers("paymentservice")[0]
