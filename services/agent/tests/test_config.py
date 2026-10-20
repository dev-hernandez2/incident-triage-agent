import pytest
from agent.config import load_settings


def test_model_defaults_to_cheap_tier_haiku(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MODEL", raising=False)
    settings = load_settings()
    assert settings.model == "claude-haiku-5-5"


def test_model_is_overridable_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL", "claude-sonnet-5-5")
    settings = load_settings()
    assert settings.model == "claude-sonnet-5-5"
