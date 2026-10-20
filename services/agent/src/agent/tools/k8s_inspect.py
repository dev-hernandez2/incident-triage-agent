"""describe_resource, get_events, list_pods tools."""

import json
from typing import Literal

from pydantic import BaseModel, Field

from agent.tools.base import ToolSpec
from agent.tools.k8s_client import K8sReadOnlyClient


class DescribeResourceInput(BaseModel):
    kind: Literal["pod", "deployment"]
    name: str
    namespace: str


class GetEventsInput(BaseModel):
    namespace: str
    since: str = Field(description="RFC3339 timestamp; events before this are omitted")


class ListPodsInput(BaseModel):
    namespace: str
    selector: str | None = Field(default=None, description="Kubernetes label selector")


def make_describe_resource(client: K8sReadOnlyClient) -> ToolSpec:
    def handler(args: BaseModel) -> str:
        assert isinstance(args, DescribeResourceInput)
        if args.kind == "pod":
            resource = client.describe_pod(args.name, args.namespace)
        else:
            resource = client.describe_deployment(args.name, args.namespace)
        metadata = resource.get("metadata")
        if isinstance(metadata, dict):
            metadata.pop("managedFields", None)
        return json.dumps(resource, default=str)

    return ToolSpec(
        name="describe_resource",
        description="Describe a Kubernetes pod or deployment, like `kubectl describe`.",
        input_model=DescribeResourceInput,
        timeout_s=10.0,
        handler=handler,
    )


def make_get_events(client: K8sReadOnlyClient) -> ToolSpec:
    def handler(args: BaseModel) -> str:
        assert isinstance(args, GetEventsInput)
        events = client.get_events(args.namespace)
        recent = [_summarize_event(e) for e in events if _event_after(e, args.since)]
        return json.dumps(recent, default=str)

    return ToolSpec(
        name="get_events",
        description="List recent Kubernetes events in a namespace.",
        input_model=GetEventsInput,
        timeout_s=10.0,
        handler=handler,
    )


def make_list_pods(client: K8sReadOnlyClient) -> ToolSpec:
    def handler(args: BaseModel) -> str:
        assert isinstance(args, ListPodsInput)
        pods = client.list_pods(args.namespace, args.selector)
        summarized = [_summarize_pod(p) for p in pods]
        return json.dumps(summarized, default=str)

    return ToolSpec(
        name="list_pods",
        description="List pods in a namespace: name, phase, ready, restarts, last state.",
        input_model=ListPodsInput,
        timeout_s=10.0,
        handler=handler,
    )


def _event_after(event: dict[str, object], since: str) -> bool:
    last_timestamp = event.get("lastTimestamp") or event.get("eventTime")
    if last_timestamp is None:
        return True
    return str(last_timestamp) >= since


def _summarize_event(event: dict[str, object]) -> dict[str, object]:
    involved_object = event.get("involvedObject")
    if not isinstance(involved_object, dict):
        involved_object = {}
    return {
        "type": event.get("type"),
        "reason": event.get("reason"),
        "message": event.get("message"),
        "count": event.get("count"),
        "first_timestamp": event.get("firstTimestamp"),
        "last_timestamp": event.get("lastTimestamp") or event.get("eventTime"),
        "involved_object": {
            "kind": involved_object.get("kind"),
            "name": involved_object.get("name"),
        },
    }


def _summarize_pod(pod: dict[str, object]) -> dict[str, object]:
    metadata = pod.get("metadata") or {}
    status = pod.get("status") or {}
    assert isinstance(metadata, dict)
    assert isinstance(status, dict)
    container_statuses = status.get("containerStatuses") or []
    assert isinstance(container_statuses, list)

    ready_count = sum(1 for c in container_statuses if c.get("ready"))
    restarts = sum(c.get("restartCount", 0) for c in container_statuses)
    last_states = [
        c.get("lastState")
        for c in container_statuses
        if c.get("lastState") and any(c["lastState"].values())
    ]

    return {
        "name": metadata.get("name"),
        "phase": status.get("phase"),
        "ready": f"{ready_count}/{len(container_statuses)}",
        "restarts": restarts,
        "last_state": last_states[0] if last_states else None,
    }
