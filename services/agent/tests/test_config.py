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


def test_load_settings_reads_metrics_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("METRICS_PORT", "9200")
    settings = load_settings()
    assert settings.metrics_port == 9200


def test_load_settings_defaults_metrics_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("METRICS_PORT", raising=False)
    settings = load_settings()
    assert settings.metrics_port == 9100


def test_load_settings_reads_otel_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://langfuse:4318")
    settings = load_settings()
    assert settings.otel_exporter_otlp_endpoint == "http://langfuse:4318"


def test_load_settings_defaults_otel_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    settings = load_settings()
    assert settings.otel_exporter_otlp_endpoint == "http://localhost:4318"
