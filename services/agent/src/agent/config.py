"""Env-driven settings for the agent service. Never hardcode these values."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    prometheus_url: str
    loki_url: str
    allowed_namespaces: frozenset[str]
    model: str


def load_settings() -> Settings:
    namespaces = os.environ.get("TRIAGE_ALLOWED_NAMESPACES", "boutique")
    return Settings(
        prometheus_url=os.environ.get("PROMETHEUS_URL", "http://localhost:9090"),
        loki_url=os.environ.get("LOKI_URL", "http://localhost:3100"),
        allowed_namespaces=frozenset(ns.strip() for ns in namespaces.split(",") if ns.strip()),
        model=os.environ.get("MODEL", "claude-haiku-5-5"),
    )
