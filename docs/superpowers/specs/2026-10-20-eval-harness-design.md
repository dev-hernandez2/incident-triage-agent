# Eval harness design (`make eval`)

## Status

Proposed

## Context

`services/agent` investigates alerts via `agent.investigate.investigate()`:
a plain tool-calling loop that takes `(session, incident, tools, llm_client)`
and returns `(Findings, Usage)`. `chaos/` can inject and revert five fault
scenarios against Online Boutique, each with a `ground_truth()` (root cause
label, affected service, expected fix) baked into its YAML definition
(`chaos/src/chaos/scenarios/definitions/*.yaml`). There is currently no
automated way to measure how accurately the agent diagnoses these faults,
compare model tiers, compare against non-agentic baselines, or catch an
accuracy regression in CI. `eval/README.md` describes the intended harness;
the `Makefile`'s `eval` target is a TODO stub.

This spec defines `eval/`, a new workspace package that runs the chaos
scenarios against the agent, scores the results, and reports accuracy/cost/
latency — in both live (against a real `kind` cluster) and replay (offline,
fixture-backed) modes.

## Goals

- One command (`make eval`) runs all 5 scenarios × N repeats × configured
  models unattended against a live cluster, producing a CSV + Markdown
  summary.
- Scores: root-cause correctness, explanation quality, time/tool-calls/
  tokens/cost, and whether the agent ever attempted an unsafe (mutating)
  action.
- Two baselines (rule-based "most recent change", and LLM-with-no-tools)
  scored identically, so the summary shows agent vs. baseline.
- Fixture record/replay so prompt iteration doesn't require a live cluster,
  and so CI can run a fast accuracy-regression smoke check on every PR.
- Spend guard: abort before projected cost exceeds `EVAL_BUDGET_USD`.

## Non-goals

- Driving the real Alertmanager → webhook → Kafka → agent-consumer pipeline.
  The runner calls `investigate()` directly (see Decision 1).
- Adding new Prometheus alert rules. `slow_redis` has no matching rule today
  and will synthesize its alert rather than wait on one (see Decision 3).
- Concurrent scenario execution. The spec explicitly requires scenarios run
  one at a time; the runner is a plain sequential loop.
- Changing `services/agent`, `chaos`, or `db` production code paths, beyond
  what's needed to make tool handlers wrappable for fixture recording (see
  Decision 4) — the loop and models stay as-is.

## Decisions

### 1. Call `investigate()` directly, not the full pipeline

The runner builds a `db.models.Incident` row from the fired alert and calls
`agent.investigate.investigate(session, incident, tools, llm_client)`
in-process. This is the actual unit the agent runs in production, so the
eval is faithful without requiring Alertmanager to be wired to the webhook
(it currently isn't tested/deployed end-to-end). Kafka and the webhook
service are not involved in eval runs.

### 2. Scenario → alertname mapping, polled against Prometheus

`eval/src/eval/scenarios.py` holds a static map from chaos scenario name to
the `boutique-alerts.yaml` alertname it should trigger:

| scenario       | alertname                  |
|----------------|-----------------------------|
| `crash_loop`   | `BoutiquePodCrashLooping`   |
| `oom`          | `BoutiquePodOOMKilled`      |
| `bad_deploy`   | `BoutiquePodNotReady`       |
| `cpu_throttle` | `BoutiqueCPUThrottlingHigh` |
| `slow_redis`   | `None` (no matching rule)   |

For scenarios with a real alertname, the runner polls Prometheus's
`/api/v1/alerts` (via `PROMETHEUS_URL`) until that alert is `state=firing`,
building the `Incident`'s `labels`/`annotations` from the matched alert
object — this is the same shape `webhook.schemas.to_alert_message` produces,
so the `Incident` the runner constructs is representative of a real one.

### 3. Synthesize the alert for scenarios with no rule

`slow_redis` (toxiproxy latency injection) trips no existing Prometheus
rule. For scenarios whose alertname map value is `None`, the runner skips
alert polling and builds the `Incident` immediately after `chaos inject`
returns, using the scenario's `ground_truth()` and a synthetic alertname of
`"ScenarioSyntheticAlert"` plus annotations describing the injected fault in
the same shape a Prometheus alert annotation would have (`summary`,
`description`). This keeps `slow_redis` in the eval set without inventing
new monitoring infrastructure as a side effect of this feature.

### 4. Fixture record/replay by wrapping tool handlers

Every `ToolSpec` passed into `investigate()` has a `handler: Callable[[BaseModel], str]`.
`eval/src/eval/fixtures.py` provides:

- `recording_tools(tools, fixture_path) -> list[ToolSpec]`: wraps each
  handler so that after invocation it appends
  `{"index": N, "tool": name, "args": ..., "output": ...}` to a JSON list at
  `fixture_path`. Used during live runs; the recorded file becomes that
  run's fixture.
- `replaying_tools(tools, fixture_path) -> list[ToolSpec]`: replaces each
  handler with a stub that pops the next recorded entry (in call order),
  asserts its `tool` name matches, and returns its `output` — raising if the
  fixture is exhausted or the name doesn't match. No live cluster,
  Prometheus, or Loki connection is made.

`REPLAY=1 make eval` (or `--replay` on the CLI) skips `chaos inject`/
`revert`/health-polling entirely and runs `investigate()` once per
`eval/fixtures/<scenario>/<run>.json` file found, against whichever models
are configured. This is the fast, offline, no-cluster path used for prompt
iteration and CI.

### 5. Judge is a single combined call

`eval/src/eval/scoring.py`'s LLM judge (`claude-haiku-5-5`, hardcoded as the
grader model per the spec, independent of the models under test) makes one
completion per run requesting a JSON object with `root_cause_correct: bool`,
`root_cause_reason: str`, `explanation_score: int (1-5)`, and
`explanation_reason: str`, validated via a pydantic model. This is only
invoked when the exact-match check on `root_cause` against
`ground_truth()["root_cause_label"]` fails (case/whitespace-insensitive
substring match tried first, to save judge calls on clean hits).

### 6. Unsafe-action detection via trace rows

`timed_run_tool`/`record_tool_call` already persist every tool call the
agent makes to the `tool_calls` table. After each run, the runner checks
that every recorded tool name is a member of the registry it was given
(`build_registry()`'s fixed, read-only set) — any call to a name outside
that set (there should never be one, since the model can only call schemas
it was offered) sets `unsafe_action=True`, which overrides the run's
`root_cause_correct` to `False` regardless of the judge's opinion. This is
a defense-in-depth check: it would only fire if a future change expanded
the tool registry passed into eval with something mutating.

### 7. Baselines run through the same inject/revert loop

Both baselines are scored by the same `scoring.py` path, so the Markdown
summary can show them as rows alongside each model:

- **Rule-based**: calls `make_get_events`'s handler directly (no LLM), finds
  the most-recently-timestamped event whose `reason` implies a config/image
  change (`BackOff`, `Pulled`, `Scheduled`-adjacent heuristics on the
  existing event reasons Online Boutique/k8s emits), and reports that
  object's owning resource name as `root_cause`. Wrapped into a `Findings`-
  shaped object with `confidence="low"` so it flows through scoring
  unchanged.
- **LLM-no-tools**: `LLMClient.complete()` with `tools=[]`, given only the
  alert payload (same `_alert_user_message` builder `investigate()` uses),
  asked to name the root cause and fix in one completion. No tool-call loop,
  so `tool_calls=0` for this baseline by construction.

### 8. Budget guard

The runner tracks a running `Decimal` total of every `cost_usd` incurred so
far this invocation (model completions + judge calls). Before starting the
next run, it estimates that run's cost using the mean cost-per-run observed
so far for that model (or a conservative fixed estimate before any run of
that model has completed) and aborts cleanly — writing out the CSV/summary
for whatever completed — if `running_total + estimate > EVAL_BUDGET_USD`
(env var, default `20`).

## Package layout

```
eval/
  pyproject.toml              # name = "triage-eval"; project.scripts eval = "eval.cli:app"
  prompts/judge_v1.md
  src/eval/
    __init__.py
    cli.py                    # Typer app; make eval entrypoint
    scenarios.py               # scenario -> alertname map, Incident builder
    runner.py                 # sequential inject/wait/investigate/revert/wait loop
    scoring.py                 # judge call, unsafe_action check, metric extraction
    fixtures.py                # recording_tools / replaying_tools
    baselines.py               # rule-based + LLM-no-tools baselines
    report.py                  # CSV + Markdown summary writer
  fixtures/
    <scenario>/<run>.json      # committed: enough for the CI smoke job (3 files)
  results/
    latest_summary.md          # committed baseline CI compares against
    <timestamp>.csv            # gitignored
    <timestamp>_summary.md     # gitignored
  tests/
    test_scoring.py
    test_fixtures.py
    test_baselines.py
    test_scenarios.py
```

`eval` is added to the root `pyproject.toml`'s `[tool.uv.workspace].members`.

## Data flow (live mode)

```
for model in models:
  for scenario in scenarios:
    for repeat in range(N):
      chaos inject <scenario>                       # subprocess
      alertname = SCENARIO_ALERTS[scenario]
      if alertname:
          poll Prometheus /api/v1/alerts until firing (timeout 10 min)
          incident = build_incident_from_alert(alert)
      else:
          incident = build_synthetic_incident(scenario)   # slow_redis
      tools = recording_tools(build_registry(settings), fixture_path)
      findings, usage = investigate(session, incident, tools, llm_client)
      chaos revert                                    # subprocess
      poll k8s Deployment until ready replicas == desired (health)
      result_row = score(scenario, findings, usage, trace_rows)
      append result_row
write CSV + Markdown summary
```

Replay mode (`REPLAY=1`) drops the `chaos inject/revert` and alert/health
polling steps and iterates committed fixture files instead of live
scenarios.

## Scoring fields (one row per run)

`timestamp, model, scenario, repeat, root_cause_correct, root_cause_reason,
explanation_score, explanation_reason, time_to_diagnosis_s, tool_calls,
input_tokens, output_tokens, cost_usd, unsafe_action, status`

## CI job

New job in `.github/workflows/ci.yml`:

```yaml
eval-smoke:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: astral-sh/setup-uv@v3
      with: { python-version: "3.12" }
    - run: uv sync --all-groups --all-packages
    - run: >
        uv run --package triage-eval eval --replay
        --fixtures eval/fixtures
        --models claude-haiku-5-5
      env:
        ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        EVAL_BUDGET_USD: "2"
```

The CLI compares the resulting summary's accuracy against
`eval/results/latest_summary.md` and exits non-zero on a drop. Updating that
committed baseline is a deliberate, reviewed change (bump it in the same PR
that changes the prompt/model and intentionally shifts accuracy).

## Testing

- `test_fixtures.py`: record a run against stub `ToolSpec`s, replay it,
  assert identical output and that replay makes no real calls.
- `test_scoring.py`: exact-match short-circuits the judge; mismatch path
  calls a stubbed judge client; `unsafe_action` detection on an injected
  out-of-registry trace row.
- `test_baselines.py`: rule-based baseline against a fixed `get_events`
  fixture picks the expected resource; LLM-no-tools baseline makes zero
  tool calls.
- `test_scenarios.py`: alertname map coverage (every chaos scenario name has
  an entry, `None` or real), synthetic incident builder shape.
- No test depends on a live cluster; the runner's inject/poll/revert loop is
  exercised only by the `Done when` live run, not by `pytest`.

## Open risks / follow-ups (not blocking this spec)

- `cpu_throttle` could plausibly trip either `BoutiqueCPUThrottlingHigh` or
  `BoutiqueHighP95Latency` depending on timing; the runner accepts whichever
  fires first if both are in the map's "equivalent" set — out of scope to
  resolve further here since one is a strict superset trigger of the other
  in practice (confirm during the first live run; adjust the map if it
  proves ambiguous).
- Rule-based baseline's heuristic for "most recent change" is a best-effort
  reading of existing k8s event reasons, not a new signal — expected to
  score poorly, which is the point (it's a floor, not a competitor).
