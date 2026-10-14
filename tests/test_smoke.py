"""Smoke tests: each service package must be importable."""

import importlib

import pytest

SERVICE_MODULES = ["agent.main", "bot.main", "executor.main", "webhook.main"]


@pytest.mark.parametrize("module_name", SERVICE_MODULES)
def test_service_module_imports(module_name: str) -> None:
    importlib.import_module(module_name)
