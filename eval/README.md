# eval

Offline/live eval harness: runs the `chaos/` fault scenarios against the
triage agent's `investigate()` function directly, scores root-cause
accuracy against each scenario's ground truth, and reports cost/latency.

## Usage

```bash
# Live run against a kind cluster (needs Prometheus, chaos CLI, Postgres)
make eval

# Offline replay against committed fixtures, no cluster needed
REPLAY=1 make eval

# Equivalent direct invocation, with explicit options
uv run --package triage-eval eval --replay \
  --fixtures eval/fixtures \
  --scenarios crash_loop,oom,bad_deploy \
  --repeats 1 \
  --models claude-haiku-5-5
```

Requires `ANTHROPIC_API_KEY` (and/or `OPENAI_API_KEY`) in the environment
— the agent under test and the judge model both make real completions
even in `--replay` mode, since only the k8s/observability tool calls are
replayed from fixtures, not the LLM calls. `DATABASE_URL` must point at a
reachable Postgres instance (the runner persists `Incident`/`ToolCall`
rows the same way the production agent does); default is
`postgresql://triage:triage@localhost:5432/triage`.

## Output

- `eval/results/<timestamp>.csv` — one row per run.
- `eval/results/<timestamp>_summary.md` — Markdown accuracy/cost table.
- `eval/results/latest_summary.md` — the only file of these three that's
  committed; it's the CI regression baseline. Update it deliberately
  (in the same PR that changes the prompt/model and intentionally shifts
  accuracy) rather than overwriting it from a routine run.

## CI

`.github/workflows/ci.yml`'s `eval-smoke` job replays the 3 committed
fixtures under `eval/fixtures/` on every PR and fails the build if
accuracy drops below `eval/results/latest_summary.md`'s baseline.

**This job requires an `ANTHROPIC_API_KEY` repository secret** (Settings →
Secrets and variables → Actions → New repository secret). Without it,
`secrets.ANTHROPIC_API_KEY` resolves to empty, every scenario's agent
completion fails auth, and the job reports 0% accuracy — not a code bug,
just a missing secret.

## Budget

`EVAL_BUDGET_USD` (default `20`) aborts a run before it would exceed that
spend, returning whatever results already completed rather than losing
them. `eval-smoke`'s CI invocation sets it to `2`.
