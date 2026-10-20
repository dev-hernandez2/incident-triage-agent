"""Builds the full list of tool specs the agent's tool-calling loop can call."""

from agent.config import Settings
from agent.tools.base import ToolSpec
from agent.tools.k8s_client import K8sReadOnlyClient
from agent.tools.k8s_inspect import make_describe_resource, make_get_events, make_list_pods
from agent.tools.logs import make_search_logs
from agent.tools.metrics import make_query_metrics


def build_registry(settings: Settings) -> list[ToolSpec]:
    k8s_client = K8sReadOnlyClient(settings.allowed_namespaces)
    return [
        make_query_metrics(settings.prometheus_url),
        make_search_logs(settings.loki_url),
        make_describe_resource(k8s_client),
        make_get_events(k8s_client),
        make_list_pods(k8s_client),
    ]


def schemas_for(tools: list[ToolSpec]) -> list[dict[str, object]]:
    return [tool.json_schema() for tool in tools]
