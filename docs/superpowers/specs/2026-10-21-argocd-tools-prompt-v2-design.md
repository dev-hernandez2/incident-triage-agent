# Step 8: Argo CD GitOps, new tools, prompt v2, ingestion fixes, model comparison

## Context

Step 7 (and earlier) left `bad_deploy` injecting faults via direct
Kubernetes API patches, the agent with five read-only tools, a single
`investigator_v1.md` prompt, pass-through ingestion, and an eval harness
whose last real run failed on a Postgres connection error. The chaos CLI
design doc already flagged Argo CD as explicitly out of scope "for now,"
deferred to this step
([`2026-10-13-chaos-cli-design.md`](2026-10-13-chaos-cli-design.md)).

This step has five parts, each independently buildable and testable, in
this order: GitOps migration, new tools, prompt v2 + schema change,
ingestion fixes, model comparison. Parts 2-5 depend on part 1 only where
noted (part 2's `get_deploy_history` needs Argo CD to exist; parts 3-5
don't).

## 1. Argo CD / GitOps migration

**Problem**: Online Boutique is deployed via `kubectl apply -k` directly
from this repo's `deploy/boutique/overlay/`. `bad_deploy` mutates the live
Deployment object directly via the k8s API. Neither reflects how a
GitOps-managed cluster actually diagnoses a bad deploy (via commit
history), which is the scenario this step needs to support.

**Design**:
- `deploy/boutique/` (this repo) remains the template developers edit.
- A new in-cluster **Gitea** instance (Helm release, added to `make up`)
  hosts one repo, `boutique-deploy`, containing only the
  `deploy/boutique/` subtree. `make up` pushes it once on first bring-up
  (idempotent: no-op if already present).
- A new in-cluster **Argo CD** instance (Helm release, added to
  `make up`) runs one `Application`
  (`deploy/k8s/argocd-boutique-app.yaml`, new) pointed at the
  `boutique-deploy` repo in Gitea, auto-sync enabled, targeting the
  `boutique` namespace. `make up` drops the old `kubectl apply -k` step
  for Online Boutique — Argo CD now owns that deploy.
- New module `chaos/src/chaos/git_repo.py`: clones `boutique-deploy` from
  Gitea into `chaos/.state/boutique-deploy/` on first use (idempotent),
  exposes `commit_and_push(message: str)`.
- `chaos/src/chaos/scenarios/bad_deploy.py` rewrite: `inject()` edits a
  kustomize image-tag patch in the cloned working copy's `overlay/`,
  commits, pushes. `revert()` makes a new commit restoring the prior tag,
  pushes. Both poll Argo CD's sync status (via its API) until the synced
  revision matches the pushed commit, before returning — preserving
  today's "fault is live when `inject()` returns" contract.
- Tests: `chaos/tests/test_bad_deploy.py` gets a fake git remote (local
  bare repo) and fake Argo CD sync-status responses, so the suite stays
  offline. No real Gitea/Argo CD in unit tests — only in the real
  cluster.

## 2. New tools

All three follow the existing `ToolSpec` factory pattern
(`services/agent/src/agent/tools/base.py`) and get added to
`build_registry()` (`services/agent/src/agent/tools/registry.py`).

- **`get_deploy_history(app)`** — new `services/agent/src/agent/tools/argocd.py`
  and a read-only `argocd_client.py` (API token auth, read-only Argo CD
  RBAC role). Calls Argo CD's sync-history and managed-resources-diff
  endpoints; returns the last N revisions (commit SHA, author, timestamp,
  sync status) plus a unified diff of the most recent change. Depends on
  part 1 existing.
- **`get_service_dependencies()`** — new
  `services/agent/src/agent/tools/dependencies.py`, reads a committed
  static YAML (`services/agent/config/service_graph.yaml`, new) mapping
  Online Boutique's known service graph. No live call, no network.
- **`get_runbook(alertname)`** — new top-level `runbooks/` directory, one
  Markdown file per alert matching names in
  `deploy/monitoring/boutique-alerts.yaml`. New
  `services/agent/src/agent/tools/runbooks.py` does filename-match
  retrieval; returns a "no runbook found" message (not an error) on
  miss.

## 3. Prompt v2 + hypotheses schema

**Schema** (`services/agent/src/agent/findings.py`):

```python
class Hypothesis(BaseModel):
    statement: str
    status: Literal["supported", "ruled_out"]
    evidence_ids: list[str]

class Findings(BaseModel):
    ...  # existing fields unchanged
    hypotheses: list[Hypothesis] = []
```

`root_cause` stays a single `str`; v2's prompt sets it to the literal
`"unknown"` when no hypothesis reaches medium+ confidence, and uses the
existing `ruled_out` list for "what was checked." v1 prompt runs produce
`hypotheses: []` and validate against the same schema unchanged.

**Prompt v2** (`services/agent/prompts/investigator_v2.md`, new;
`investigator_v1.md` untouched): same Method/Untrusted-data/Citing-
evidence/Confidence structure as v1, plus: track candidate hypotheses as
you investigate, mark each `supported`/`ruled_out` with evidence ids,
only promote to `root_cause` at medium+ confidence, otherwise
`root_cause="unknown"`. Mentions the three new tools as additional
evidence sources.

**Scoring "unknown" correctly**: ground-truth scenario YAML
(`chaos/src/chaos/scenarios/definitions/*.yaml` and new eval-only
fixtures) gains `diagnosable: bool = true`. Two new eval-only fixtures
are added under `eval/fixtures/` with `diagnosable: false` (insufficient/
misleading evidence by design — not chaos-derived, since every chaos
scenario is a deliberately known fault). `eval/src/eval/scoring.py`:
correct if (`diagnosable` and `root_cause` matches) or (not `diagnosable`
and `root_cause == "unknown"`). Hypothesis count/quality is reported in
the comparison table as a secondary, non-blocking metric so v1/v2 stay
comparable on the same primary accuracy metric.

## 4. Ingestion: dedup, priority, idempotency

**Dedup**: Alertmanager re-sends firing alerts each evaluation interval.
`upsert_incident` (`services/agent/src/agent/incidents.py`) already
no-ops duplicate `fingerprint`+`status="received"` writes, but the agent
still re-investigates on every duplicate today. Fix: `upsert_incident`
returns whether the write was a genuinely new incident or a no-op;
`services/agent/src/agent/main.py`'s consume loop skips investigation
entirely on a no-op. No new field, no new table.

**Idempotent on retry**: already correct — DB write is upsert-by-
fingerprint, Kafka offset commits only after DB commit. The dedup fix
above also makes retries cheap (skip investigation), not just safe.

**Critical before warning**: two Kafka topics, `alerts.raw.critical` and
`alerts.raw.warning`. `services/webhook/src/webhook/main.py` routes by
Alertmanager's `severity` label at produce time. The agent consumer
subscribes to both; each poll loop drains all currently-available
critical messages before taking one warning message, so warnings are
never fully starved.

## 5. Model comparison

**Cost projection (must be presented and approved before any live run)**:
4 models (`claude-sonnet-5-5`, `gpt-5.6-terra`, `claude-haiku-5-5`,
`gpt-5.6-luna` — all already priced in `llm/src/llm/pricing.py`) × 2
prompts × ~7 scenarios (5 chaos scenarios + 2 new undiagnosable fixtures)
× 3 repeats (matching existing CI-smoke flakiness-tolerance practice) =
168 runs. Estimated blended cost ≈ $0.09/run (scaled from the
`ci-smoke-baseline` median of $0.0294/run on haiku-tier under a smaller
5-tool/v1-only setup, ×1.5 for the larger v2 tool surface and heavier
prompt, then blended across all four models' relative `MODEL_PRICES`
rates) ≈ **$15 total**, under the $40 `EVAL_BUDGET_USD` ceiling. Recompute
from real token counts once the harness runs and present as an explicit
go/no-go checkpoint before the live run starts.

**Execution**: `--replay` (existing `eval/src/eval/fixtures.py` mechanism)
reused wherever a (scenario, tool-call-sequence) has already been
recorded, saving cost on repeated tool calls across repeats of the same
model+prompt+scenario combo.

**Output**: `eval/results/<timestamp>_model_comparison.md`, extending
`eval/src/eval/report.py`. Rows = model × prompt (8 rows); columns =
accuracy, median cost/incident, median latency, consistency (existing
metrics), plus the new undiagnosable-correct rate. Table calls out which
combo(s) clear ≥70% accuracy at <$0.50/incident.

## Out of scope

- Pushing the Gitea deploy repo to any real external remote (GitHub,
  etc.) — local-only Gitea inside the kind cluster.
- Mirroring the full incident-triage-agent repo into Gitea — only the
  `deploy/boutique/` subtree.
- Separate `FindingsV1`/`FindingsV2` schema classes — one `Findings`
  schema with an optional `hypotheses` field.
- Reordering within a single Kafka partition — priority is handled via
  two topics, not an in-process reorder buffer.
