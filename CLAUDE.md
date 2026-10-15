# triage-agent

AI agent that investigates Kubernetes alerts with read-only tools and posts a
root-cause summary to Discord for human approval before any remediation runs.
Portfolio project.

## Architecture decisions

- **Demo app**: Google's Online Boutique (`microservices-demo`), deployed on a
  local `kind` cluster. No other demo apps.
- **Agent runtime**: a plain LLM SDK tool-calling loop, implemented directly
  against the Anthropic/OpenAI SDKs. No LangGraph, CrewAI, AutoGen, or other
  agent framework. See `docs/adr/0001-agent-framework.md`.
- **Models**: configurable, not hardcoded.
  - Default candidates: Claude Sonnet 5.5, gpt-5.6-terra
  - Cheap tier (default for local dev): Claude Haiku 5.5, gpt-5.6-luna
  - Model choice is a config value (env var / settings), never hardcoded in
    agent logic.
- **Notifications & approvals**: Discord bot. The agent posts its root-cause
  summary to a Discord channel; a human approves or denies before any
  remediation action is taken.
- **Pipeline**: Alertmanager webhook -> FastAPI (`services/webhook`) ->
  Kafka topic `alerts.raw` -> agent (`services/agent`) consumes and
  investigates.
- **Storage**: Postgres. Used for incidents, tool-call traces, and approval
  records.
- **Language**: Python 3.12. Type hints everywhere; `mypy` enforced in CI.

## Safety rules

- The agent (`services/agent`) is **read-only**. It may only call
  observability/inspection tools (e.g. `kubectl get`, `kubectl logs`, metrics
  queries). It must never have access to any mutating tool.
- Only `services/executor` may change cluster state, and only after explicit
  human approval recorded via the Discord bot.
- Never commit secrets. Real credentials live in `.env` (gitignored); only
  `.env.example` with placeholder keys is committed.

## Budget

- Target LLM spend: **$50/month**.
- Default to cheap-tier models (Haiku 5.5 / gpt-5.6-luna) for local
  development and iteration. Reserve default-tier models (Sonnet 5.5 /
  gpt-5.6-terra) for deliberate evals or demos.

## Conventions

- Dependency management: `uv` (single root `pyproject.toml` workspace across
  `services/*` and `chaos`). The root project has no dependencies of its
  own, so a bare `uv sync`/`uv run` only resolves that empty closure and
  silently skips every workspace member. Always pass `--all-packages`
  (`uv sync --all-packages`, `uv run --all-packages pytest`, etc.) except
  where a command intentionally targets a single member package.
- Lint/type-check: `ruff` + `mypy` (`strict = true`, enforced repo-wide
  including test files).
- Tests: `pytest`.
- Commits: small, atomic, one logical change each.

## Layout

```text
services/webhook/   FastAPI receiver: Alertmanager webhook -> Kafka
services/agent/      Tool-calling loop; read-only k8s/observability tools
services/executor/   Only service permitted to mutate cluster state
services/bot/        Discord bot: posts summaries, handles approve/deny
chaos/               Typer CLI (`chaos`): injects/reverts fault scenarios
                     against Online Boutique, with YAML ground truth per
                     scenario. See chaos/README.md.
eval/                Offline eval harness for agent accuracy
deploy/k8s/          Raw k8s manifests (kind-friendly)
deploy/helm/         Helm charts
docs/adr/            Architecture decision records
tests/               Cross-service / integration tests
```
