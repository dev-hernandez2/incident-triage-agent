"""Plain tool-calling loop that investigates alerts with read-only tools.

No agent framework (LangGraph, CrewAI, etc.) — see docs/adr/0001-agent-framework.md.
Model is a config value, not hardcoded.
"""


def run_investigation(alert: dict[str, str]) -> str:
    # TODO: tool-calling loop against read-only k8s/observability tools
    raise NotImplementedError
