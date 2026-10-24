# Public release prep — design

Date: 2026-10-23

## Goal

Prepare `triage-agent` for public release: a real `make demo`, a Helm
chart covering all five services, three new ADRs, a cleanup pass, and a
README + blog post that describe the repo as it actually is. Making the
GitHub repo public, recording the demo video, and updating
hernandez2.com are **out of scope** for this work — the user will do
those themselves once the deliverables below exist.

## Current state (verified 2026-10-23)

- All five services (`webhook`, `agent`, `bot`, `executor`, `dashboard`)
  are implemented, each with its own `pyproject.toml`, `src/`, `tests/`.
  `dashboard/` (the Vite+React frontend) also exists.
- `chaos` CLI is implemented and documented (`chaos/README.md`): 5
  scenarios (`crash_loop`, `oom`, `bad_deploy`, `cpu_throttle`,
  `slow_redis`).
- `eval/` harness is implemented, runs in CI (`.github/workflows/ci.yml`
  `eval-smoke` job), and has one committed baseline:
  `eval/results/latest_summary.md` — `ci-smoke-baseline`, 50% accuracy,
  9 runs, median $0.0294/run, median 12.4s. No cross-model comparison
  has been run.
- `docs/adr/` has 0001 (agent framework choice) and 0002 (observability
  + network hardening). Numbers 0003–0005 are free.
- `deploy/k8s/` has raw manifests for `triage-agent` and
  `triage-executor` only (Deployment, Service, RBAC, NetworkPolicy) plus
  cluster bootstrap (kind config, Gitea/ArgoCD values). `webhook`, `bot`,
  `dashboard` have no k8s manifests yet at all.
- `deploy/helm/` only has values files for the Kafka/Postgres Bitnami
  charts consumed by `make up` — no chart of our own exists.
- `Makefile`'s `demo` target is a literal `@echo "TODO: ..."` stub.
  `up`, `down`, `eval`, `test`, `lint` are real.
- No `LICENSE`, no `CONTRIBUTING.md`. No secret has ever been committed
  (`.env` never appears in history; `.env.example` has placeholders
  only).
- README is a 26-line stub that already honestly states `make demo` is
  pending.

## Decisions carried from clarifying questions

1. **Combined plan, dependency order.** One spec (this doc) → one
   `writing-plans` implementation plan, ordered: `make demo` → Helm
   chart → ADRs → cleanup pass → README/blog. README/blog go last
   because they describe real demo output, real eval numbers, and a
   real Helm chart — writing them first would mean rewriting them.
2. **External actions (public repo, video, portfolio site) are not
   done by Claude.** The README and `make demo` script are written so
   the user can do those steps themselves immediately afterward.
3. **Helm chart replaces the raw `deploy/k8s/` app-service manifests.**
   `deploy/helm/triage-agent/` becomes the one way to deploy
   webhook/agent/bot/executor/dashboard, including their RBAC and
   NetworkPolicies. `make up` is updated to `helm upgrade --install` the
   chart instead of `kubectl apply -f` the raw manifests. The
   `kind-config.yaml`, Gitea/ArgoCD/Kafka/Postgres bootstrapping in
   `make up` is untouched — only the triage app services move to Helm.
4. **Executor's target namespace is a values.yaml setting**
   (`executor.targetNamespace`, default `boutique`), independent of the
   namespace the chart itself installs into (`triage`, via
   `--namespace`/`.Release.Namespace`). The agent's ClusterRole is
   unconditionally cluster-wide and does not reference this setting at
   all, per CLAUDE.md — only the executor's namespaced Role/RoleBinding
   are templated against it.
5. **`make demo` starts the app services itself.** It launches
   webhook/agent/bot/executor/dashboard (as local `uv run` background
   processes, consistent with how `make up`'s help text already tells
   users to run services locally against forwarded ports — see Makefile
   `up` target's final `@echo` block), injects `bad_deploy`, waits,
   prints Discord/dashboard URLs, then reverts and stops the services it
   started. This keeps `make demo` fully self-contained from a fresh
   `make up`.
6. **Eval numbers in the README are the real, current ones.** The
   README's eval table shows `ci-smoke-baseline` (0.50 accuracy, Haiku
   tier) as-is. A line in Limitations states cross-model comparison
   (Sonnet 5.5 vs Haiku 5.5, Claude vs GPT) has not been run, rather
   than fabricating numbers or spending eval budget to generate them in
   this pass.

## Deliverables

### 1. `make demo`

A new script, `scripts/demo.sh` (invoked by the `demo:` Makefile
target), that:

1. Checks the `triage` kind cluster is up (fails with a clear message
   pointing at `make up` if not).
2. Starts `webhook`, `agent`, `bot`, `executor`, `dashboard` as
   background `uv run --package <name> ...` processes, each with its
   stdout/stderr redirected to `/tmp/triage-demo-<service>.log`, against
   the same forwarded ports `make up`'s help text documents
   (Kafka/Postgres/Prometheus/Loki via `kubectl port-forward`, started
   here if not already running — reuse the same port-forward pattern
   `make up` uses for Gitea/Postgres).
3. Waits for each service's health/readiness (a simple TCP/HTTP
   poll loop per service, bounded retries, matching existing Makefile
   poll style).
4. Runs `uv run --all-packages chaos inject bad_deploy --service
   <demo-target-service>`.
5. Prints: the Discord channel to watch (from `DISCORD_CHANNEL_ID` in
   the environment) and the dashboard URL
   (`http://localhost:<dashboard-port>`), plus roughly how long the
   agent/bot/approval flow takes to appear.
6. Waits (bounded timeout, e.g. 5 minutes) for a terminal state — either
   polls the `incidents`/`actions` tables via the dashboard's read API,
   or simply sleeps a fixed, documented duration — then runs `chaos
   revert`.
7. On exit (success, failure, or Ctrl-C), stops every background
   process it started and kills any port-forwards it started, via a
   `trap` cleanup — never leaves orphaned processes.

This is the script for the 2-minute demo video; it does not record
video itself.

### 2. Helm chart: `deploy/helm/triage-agent/`

Standard chart layout:

```text
deploy/helm/triage-agent/
  Chart.yaml
  values.yaml
  templates/
    _helpers.tpl
    serviceaccount-agent.yaml
    clusterrole-agent.yaml          # cluster-wide get/list/watch, unconditional
    clusterrolebinding-agent.yaml
    serviceaccount-executor.yaml
    role-executor.yaml              # namespaced Role in .Values.executor.targetNamespace
    rolebinding-executor.yaml
    networkpolicy-agent.yaml        # ported from deploy/k8s/networkpolicy-agent.yaml
    networkpolicy-executor.yaml     # ported from deploy/k8s/networkpolicy-executor.yaml
    deployment-webhook.yaml
    deployment-agent.yaml
    deployment-bot.yaml
    deployment-executor.yaml
    deployment-dashboard.yaml
    service-webhook.yaml
    service-agent.yaml               # metrics Service, ported as-is
    service-dashboard.yaml
    servicemonitor-agent.yaml        # ported from grafana-dashboard-agent.yaml's ServiceMonitor piece
    secret.yaml                      # templated from .Values.secrets, or `existingSecret` passthrough
  README.md
```

Key `values.yaml` fields (CLAUDE.md asks for "values for model, budgets
and namespaces"):

```yaml
namespace: triage              # install namespace (normally set via --namespace)
executor:
  targetNamespace: boutique    # namespace the executor's Role/RoleBinding target

models:
  default: claude-sonnet-5-5
  cheap: claude-haiku-5-5
  tier: cheap                  # cheap | default — maps to LLM_MODEL env on agent

budget:
  monthlyUsd: 50

image:
  repository: triage           # e.g. ghcr.io/<user>/triage, templated per-service as "<repository>-<service>"
  tag: latest
  pullPolicy: IfNotPresent

existingSecretName: ""          # if set, skip templating secret.yaml and reference this Secret instead
secrets: {}                     # else, stringData for the templated Secret (dev/demo only)

kafka:
  bootstrapServers: kafka.kafka.svc.cluster.local:9092
prometheus:
  url: http://prometheus-operated.monitoring.svc.cluster.local:9090
loki:
  url: http://loki.monitoring.svc.cluster.local:3100
```

RBAC templates carry over the exact rules and the "why separate /
why narrow" comments from the existing `deploy/k8s/rbac-triage-*.yaml`
files (agent: cluster-wide `get/list/watch` only, never secrets or
mutating verbs; executor: namespaced `Role` in
`.Values.executor.targetNamespace`, `get/list/patch` on `deployments`
only). NetworkPolicies port the existing agent/executor policies
verbatim (including the ADR-0002 comment about the broad LLM-API egress
CIDR being a known, accepted limitation).

`deploy/k8s/` manifests superseded by the chart
(`deployment-agent.yaml`, `deployment-executor.yaml`,
`service-agent.yaml`, `rbac-triage-agent.yaml`, `rbac-triage-executor.yaml`,
`networkpolicy-agent.yaml`, `networkpolicy-executor.yaml`,
`grafana-dashboard-agent.yaml`, `secrets-example.yaml`) are deleted;
`kind-config.yaml`, `gitea-values.yaml`, `argocd-boutique-app.yaml`
stay (cluster bootstrap, unrelated to the app services).

`Makefile`'s `up` target: replace the
`kubectl apply -f deploy/k8s/rbac-triage-agent.yaml` /
`rbac-triage-executor.yaml` / (no app Deployments were ever applied by
`make up` before — services were run locally) block with one
`helm upgrade --install triage-agent deploy/helm/triage-agent --namespace
triage -f <values file>` call, after the Kafka/Postgres installs it
already depends on. The final `@echo` help block is updated to mention
`helm` instead of raw `kubectl apply` where relevant.

### 3. ADRs

- **0003-kafka-for-ingestion.md** — why the webhook→agent hop goes
  through Kafka (`alerts.raw` topic) rather than a direct HTTP call or
  a different queue (SQS, Redis streams, RabbitMQ). Covers: decoupling
  webhook availability from agent processing time, replay/backpressure
  during agent investigation, and why a single-partition/simple-consumer
  setup is sufficient for this scale rather than needing Kafka's
  partitioning story.
- **0004-read-only-agent-separate-executor.md** — formalizes the
  split already implemented and described in CLAUDE.md's Safety rules:
  why two services with two separate ServiceAccounts/RBAC identities
  instead of one service with conditional mutation logic, and why that
  split is load-bearing for the human-approval guarantee (a compromised
  or misbehaving agent literally cannot mutate the cluster, regardless
  of what the LLM outputs).
- **0005-model-choice.md** — records the configurable
  default/cheap-tier model choice (Claude Sonnet 5.5 / Haiku 5.5,
  gpt-5.6-terra / gpt-5.6-luna) and includes the real
  `eval/results/latest_summary.md` baseline number (50% accuracy,
  Haiku tier, 9 runs) as the evidence available today, explicitly
  noting that a full cross-tier comparison is future work, not yet
  run.
- **0006-online-boutique-demo-app.md** — the pasted request calls
  this "0005" but 0005 is taken by model choice per the ordering above;
  it becomes 0006. Documents why Online Boutique was chosen (realistic
  polyglot microservices topology, existing Prometheus/Grafana
  community dashboards, well-known enough that reviewers don't need to
  learn an unfamiliar app) and that no other demo app is supported, per
  CLAUDE.md.

Each ADR follows the existing 0001/0002 format (read both first for
exact structure/headings before writing).

### 4. Cleanup pass

- `ruff check .` and `mypy` (strict, repo-wide) must pass; fix findings
  rather than suppressing them.
- `uv run --all-packages pytest` (full repo, no path arg — per
  CLAUDE.md's note about the `tests/__init__.py` collision) must pass.
- `dashboard/`: `npx tsc -b` and `npx vitest run` must pass.
- Search for dead code (unused functions/imports/files) introduced
  across prior steps; remove.
- Verify no secrets in git history: confirm `.env` never committed
  (already checked — clean) and spot-check for any hardcoded
  tokens/keys in tracked files via a broad grep before finalizing.
- Add `LICENSE` (MIT, user as copyright holder).
- Add `CONTRIBUTING.md`: how to run tests/lint, branch/commit
  conventions (small atomic commits, per CLAUDE.md), how to open a PR,
  pointer to `docs/adr/` for architectural changes.

### 5. README.md

Rewrite in place, sections in the order requested:

1. One-paragraph pitch.
2. Architecture diagram (Mermaid) — Alertmanager → webhook → Kafka
   `alerts.raw` → agent → Discord bot / dashboard → executor → cluster,
   matching CLAUDE.md's Pipeline section and the real service names.
3. 90-second quickstart: `make up`, `make demo`, `make eval` — exact
   commands, no placeholders.
4. Latest eval results table (real numbers from
   `eval/results/latest_summary.md`) with a note on the model-comparison
   gap (decision 6 above).
5. Key design decisions — short bullets each linking to the relevant
   `docs/adr/000N-*.md` file (1 through 6).
6. Safety model — condensed from CLAUDE.md's Safety rules section:
   read-only agent, separate executor, typed non-executable `manual`
   action, audit log, dashboard's live role re-check.
7. Cost per incident — derived from the real eval baseline
   (`$0.0294` median cost/run as the current empirical per-incident
   cost at Haiku tier; cross-reference the $50/month budget target).
8. Limitations — honest list: 50% eval accuracy baseline is early/small
   sample (9 runs, 3 fixtures), 7 of the eval scenarios are synthetic
   fixtures not validated against a live cluster (per `eval/README.md`),
   no cross-model comparison yet, LLM-API NetworkPolicy egress is
   IP-range-based not FQDN-based (ADR-0002's accepted limitation), no
   multi-cluster/multi-tenant support.

### 6. `docs/blog.md`

Narrative draft, sections: problem (alert fatigue / unsafe
auto-remediation), architecture (same pipeline as README, more prose),
how the eval works (fixtures vs. live recordings, scoring against
ground truth, budget guard), results including failures (the 50%
baseline honestly discussed — which scenarios it gets right/wrong if
visible in `eval/results/20261021T000231Z.csv`, check that file for
per-scenario breakdown before writing), lessons learned (a few genuine
technical lessons from the safety-split architecture and eval design —
written after the other deliverables exist, not speculated now).

## Testing / verification

- `make demo` is tested by actually running it against a live kind
  cluster (`make up` first) and confirming: services start,
  `bad_deploy` injects, Discord message appears (manual visual check,
  since Discord posting isn't mockable in CI), dashboard shows the
  incident, revert succeeds, all background processes/port-forwards are
  cleaned up on exit.
- Helm chart is tested with `helm lint deploy/helm/triage-agent` and a
  real `helm install --dry-run` against the kind cluster's API server,
  then a real `helm upgrade --install` as part of re-running `make up`
  end-to-end.
- ADRs: no test, reviewed for accuracy against the actual implemented
  code they describe.
- Cleanup: `ruff`, `mypy`, `pytest` (full repo), `tsc -b`, `vitest run`
  all pass; these are the acceptance gates.
- README/blog: no automated test; verified by literally following the
  README's quickstart on a clean checkout (the task's own "done when"
  criterion: "a fresh clone reaches a working demo by following only
  the README").

## Out of scope

- Making the GitHub repo public.
- Recording the demo video.
- Updating hernandez2.com.
- Running a real cross-model eval comparison (documented as a known
  gap instead).
