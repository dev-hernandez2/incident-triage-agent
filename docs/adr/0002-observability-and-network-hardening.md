# ADR 0002: Observability stack and network hardening choices

## Status

Accepted

## Context

The agent and executor had no metrics, tracing, or network-level
egress restrictions. This ADR records the choices made to add them.

## Decisions

### Metrics: Prometheus client library, not a sidecar

`obs/src/obs/metrics.py` uses `prometheus_client` directly inside the
agent process (`start_http_server`) rather than a sidecar exporter.
The agent already has no HTTP server (it's a Kafka consumer loop), so
a single stdlib-based exposition endpoint is simpler than introducing
an ASGI app or sidecar just to serve `/metrics`.

### Tracing: OpenTelemetry SDK, exported via OTLP to self-hosted Langfuse

Langfuse v3 accepts OTLP natively, so no Langfuse-specific SDK is
needed beyond the standard `opentelemetry-sdk` +
`opentelemetry-exporter-otlp` packages. Spans wrap the existing
`investigate()` call, each `llm_client.complete()` call, and each tool
call — no restructuring of the hand-rolled loop (see ADR 0001).

### Langfuse deployment: docker-compose, not in-cluster Helm

Self-hosted Langfuse v3 needs Postgres + ClickHouse + Redis. Running
all of that inside the kind cluster alongside the existing Prometheus/
Loki/Argo CD/Kafka stack is disproportionate for a portfolio project.
Langfuse instead runs via `deploy/langfuse/docker-compose.yaml` outside
the cluster; the agent's `OTEL_EXPORTER_OTLP_ENDPOINT` points at its
exposed OTLP port.

### NetworkPolicy LLM egress: 0.0.0.0/0:443, not hostname-scoped

Kubernetes `NetworkPolicy` cannot filter egress by hostname — only by
IP block, namespace, or pod selector. Scoping the agent's LLM API
calls to just `api.anthropic.com`/`api.openai.com` would require an
FQDN-aware CNI (e.g. Cilium's `toFQDNs`), which this project doesn't
run (kind's default CNI). The agent's NetworkPolicy
(`deploy/k8s/networkpolicy-agent.yaml`) therefore allows egress to any
IP on port 443, which is broader than ideal — it does not prevent the
agent process from making an arbitrary HTTPS call to anywhere, only
from doing so on other ports or via other protocols. This is an
accepted limitation: closing it fully is future work contingent on a
CNI upgrade, out of scope here.

### Deployment manifests added now, not deferred

Secrets and NetworkPolicies have no effect without something running
in-cluster for them to attach to. `deploy/k8s/deployment-agent.yaml`
and `deployment-executor.yaml` were added in this same change so the
hardening is actually enforced, not just written and left unattached.

## Consequences

- The agent now exposes `/metrics` (port 9100, configurable via
  `METRICS_PORT`) and emits OTel spans (configurable via
  `OTEL_EXPORTER_OTLP_ENDPOINT`) — both are config values, not
  hardcoded, consistent with the project's existing model-choice
  convention.
- Running the full stack locally now requires `docker compose -f
  deploy/langfuse/docker-compose.yaml up` in addition to the kind
  cluster, if trace export is desired.
- The LLM-egress NetworkPolicy limitation means the agent's
  NetworkPolicy alone does not fully prevent data exfiltration over
  HTTPS; this relies on the agent's own code never doing so, not on
  the network layer enforcing it.
