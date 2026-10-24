# triage-agent

AI agent that investigates Kubernetes alerts with read-only tools and posts a
root-cause summary to Discord for human approval before any remediation runs.
The agent's suggested fix is a typed action (rollback/restart/scale/manual);
a human approves or rejects it via Discord buttons or a web dashboard before
`services/executor` ever touches the cluster. Portfolio project.

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
- **Notifications & approvals**: Discord bot posts the root-cause summary
  with Approve/Reject buttons (reject requires a reason, via a modal) to a
  Discord channel; only members with the configured approver role
  (`DISCORD_APPROVER_ROLE_ID`) may approve/reject. A `services/dashboard`
  web UI (Discord OAuth2 login) offers the same approve/reject actions,
  re-checking the caller's live Discord role on every write request rather
  than trusting a cached session claim. Both entry points call the same
  shared `bot.actions.approve_action`/`reject_action` functions — there is
  exactly one place that enforces the approval rule.
- **Remediation action schema**: the agent's `suggested_fix` is a typed,
  discriminated Pydantic union — `rollback`, `restart`, `scale`, or
  `manual` (free text, never executable) — enforced at the LLM tool-call
  boundary, not free text. An approved action is tracked as an `actions`
  row and executed by `services/executor` only; `manual` actions are never
  offered an Approve control and are independently refused if ever claimed.
- **Pipeline**: Alertmanager webhook -> FastAPI (`services/webhook`) ->
  Kafka topic `alerts.raw` -> agent (`services/agent`) consumes and
  investigates -> Discord bot / dashboard records approval ->
  `services/executor` polls for approved actions, executes them, and
  watches the triggering incident for up to 5 minutes for it to resolve.
- **Storage**: Postgres. Tables: `incidents`, `tool_calls`, `findings`,
  `actions` (approval lifecycle per proposed remediation), `audit_log`
  (append-only: every tool call, model call, approval, rejection, and
  executed action).
- **Language**: Python 3.12 for all services (type hints everywhere; `mypy`
  enforced in CI). `dashboard/` is a separate TypeScript + React (Vite)
  frontend, not part of the Python workspace.

## Safety rules

- The agent (`services/agent`) is **read-only**. It may only call
  observability/inspection tools (e.g. `kubectl get`, `kubectl logs`, metrics
  queries). It must never have access to any mutating tool. Its RBAC
  ServiceAccount (`deploy/helm/triage-agent/templates/clusterrole-agent.yaml`,
  `clusterrolebinding-agent.yaml`, `serviceaccount-agent.yaml`) is a
  cluster-wide `ClusterRole` granting only `get`/`list`/`watch`.
- Only `services/executor` may change cluster state, and only after an
  `actions` row has been approved via the Discord bot or the dashboard.
  Its RBAC ServiceAccount (`deploy/helm/triage-agent/templates/role-executor.yaml`,
  `rolebinding-executor.yaml`, `serviceaccount-executor.yaml`) is a
  separate, narrower identity: a namespaced `Role` in the `boutique`
  namespace only, granting `get`/`list`/`patch` on `deployments` — nothing
  else, and no access outside that namespace.
- A `manual`-typed action is never executable: no UI may offer an
  Approve control for one, and `services/executor` independently refuses
  to execute a `manual` action even if one is ever claimed.
- Every tool call, model call, approval, rejection, and executed action
  must have a corresponding `audit_log` row; `eval/` has a safety check
  (`eval.unsafe_actions.check_unsafe_actions`) that queries the live
  `actions`/`audit_log` tables and fails if any executed/failed action
  lacks a prior approval record.
- The dashboard's session cookie carries only the Discord user id, never
  a cached role list — every write endpoint re-checks the caller's
  current Discord guild role live, so a revoked role loses access on the
  very next request, not just at next login.
- Never commit secrets. Real credentials live in `.env` (gitignored); only
  `.env.example` with placeholder keys is committed.

## Budget

- Target LLM spend: **$50/month**.
- Default to cheap-tier models (Haiku 5.5 / gpt-5.6-luna) for local
  development and iteration. Reserve default-tier models (Sonnet 5.5 /
  gpt-5.6-terra) for deliberate evals or demos.

## Conventions

- Dependency management: `uv` (single root `pyproject.toml` workspace across
  `services/*`, `chaos`, `db`, `llm`, `obs`, and `eval`). The root project
  has no dependencies of its own, so a bare `uv sync`/`uv run` only
  resolves that empty closure and silently skips every workspace member.
  Always pass `--all-packages` (`uv sync --all-packages`, `uv run
  --all-packages pytest`, etc.) except where a command intentionally
  targets a single member package (`uv run --package <name> pytest ...`).
- Cross-service plumbing (DB engine construction, session commit/rollback/
  close, structured JSON logging) lives in `db.engine`/`db.session` and
  `obs.logging`, not duplicated per service. A new service wires these in
  rather than writing its own `create_engine`/session-loop/log-formatter.
- `dashboard/` is a separate Vite + React + TypeScript app, NOT part of the
  `uv` workspace — it has its own `package.json`/npm toolchain. Run its
  checks from inside that directory (`npm run dev`, `npx vitest run`,
  `npx tsc -b`).
- No `services/*/tests` directory (nor `chaos/tests`, `db/tests`,
  `eval/tests`, `llm/tests`) has an `__init__.py` — adding one collides
  with the root `tests/__init__.py` under pytest's prepend import mode
  the moment the full-repo suite runs. Always verify a new test directory
  against `uv run --all-packages pytest` (no path argument) before
  committing, not just that package's own scoped test run — a package-
  scoped run cannot surface this class of collision.
- Lint/type-check: `ruff` + `mypy` (`strict = true`, enforced repo-wide
  including test files).
- Tests: `pytest` (Python services), `vitest` (`dashboard/`).
- Commits: small, atomic, one logical change each.

## Layout

```text
services/webhook/    FastAPI receiver: Alertmanager webhook -> Kafka
services/agent/      Tool-calling loop; read-only k8s/observability tools
services/executor/   Only service permitted to mutate cluster state;
                     polls approved actions, executes, watches recovery
services/bot/        Discord bot: posts summaries with Approve/Reject
                     buttons + reject-reason modal; bot/actions.py holds
                     the shared approve/reject logic also used by the
                     dashboard
services/dashboard/  FastAPI read API + Discord OAuth2 login; same
                     approve/reject actions as the bot, role-gated
dashboard/           Vite + React + TypeScript frontend for
                     services/dashboard (separate npm toolchain)
db/                  Shared SQLAlchemy models + Alembic migrations
                     (incidents, tool_calls, findings, actions, audit_log);
                     also db.engine (engine_from_env) and db.session
                     (session_scope) shared by every service
llm/                 Thin wrapper over the Anthropic/OpenAI SDKs
obs/                 Shared structured JSON logging (obs.logging.
                     configure_logging), used by every service
chaos/               Typer CLI (`chaos`): injects/reverts fault scenarios
                     against Online Boutique, with YAML ground truth per
                     scenario. See chaos/README.md.
eval/                Offline eval harness for agent accuracy, plus the
                     "0 unsafe actions" safety check against the live
                     actions/audit_log tables
deploy/k8s/          kind-cluster/GitOps bootstrap manifests only
                     (kind-config.yaml, gitea-values.yaml,
                     argocd-boutique-app.yaml); the triage-agent app
                     services' RBAC, NetworkPolicies, and Deployments
                     live in deploy/helm/triage-agent/ instead
deploy/helm/         Helm chart (triage-agent/) deploying all five app
                     services plus their RBAC and NetworkPolicies
docs/adr/            Architecture decision records
docs/superpowers/    Design specs and implementation plans for larger
                     features (brainstorming/writing-plans skill output)
tests/               Cross-service / integration tests
```
