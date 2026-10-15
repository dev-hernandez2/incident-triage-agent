import json
from pathlib import Path

import pytest
from chaos.state import ActiveInjection, StateCorruptError, StateStore


def test_load_returns_none_when_no_file(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "active.json")
    assert store.load() is None


def test_save_then_load_round_trips(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "active.json")
    injection = ActiveInjection(
        scenario="oom",
        service="cartservice",
        namespace="boutique",
        injected_at="2026-10-13T00:00:00+00:00",
        saved_state={"containers": [{"name": "cartservice"}]},
    )
    store.save(injection)

    loaded = store.load()
    assert loaded == injection


def test_clear_removes_the_file(tmp_path: Path) -> None:
    path = tmp_path / "active.json"
    store = StateStore(path)
    store.save(
        ActiveInjection(
            scenario="oom", service="cartservice", namespace="boutique",
            injected_at="2026-10-13T00:00:00+00:00", saved_state={},
        )
    )
    assert path.exists()

    store.clear()
    assert not path.exists()
    assert store.load() is None


def test_clear_is_a_noop_when_nothing_active(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "active.json")
    store.clear()  # must not raise


def test_load_raises_on_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "active.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json")

    store = StateStore(path)
    with pytest.raises(StateCorruptError):
        store.load()


def test_load_raises_on_valid_json_missing_fields(tmp_path: Path) -> None:
    path = tmp_path / "active.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"scenario": "oom"}))

    store = StateStore(path)
    with pytest.raises(StateCorruptError):
        store.load()
