# Eval Harness (`make eval`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `eval/`, a new workspace package that runs the 5 chaos
scenarios against the triage agent (directly via `investigate()`), scores
accuracy/cost/latency with an LLM judge, compares against two baselines,
supports offline fixture replay, enforces a spend budget, and wires into
`make eval` plus a CI smoke job.

**Architecture:** A sequential runner (`eval.runner`) drives
`chaos inject` → poll Prometheus for the alert (or synthesize one) → build
a `db.models.Incident` → call `agent.investigate.investigate()` with
tool handlers wrapped for fixture recording → `chaos revert` → poll k8s
health → score the run. Scoring (`eval.scoring`) does exact-match-first,
judge-call-on-miss. Two baselines (`eval.baselines`) reuse the same
scoring path. `eval.fixtures` provides the record/replay tool-handler
wrappers. `eval.report` writes CSV + Markdown. `eval.cli` (Typer) is the
`make eval` / CI entrypoint.

**Tech Stack:** Python 3.12, existing workspace packages (`db`, `llm`,
`agent` via `services/agent`, `chaos`), Typer, pydantic, SQLAlchemy,
pytest, `uv` workspace.

**Spec:** `docs/superpowers/specs/2026-10-20-eval-harness-design.md`

## Global Constraints

- Dependency management: `uv`, single root workspace. Use
  `uv sync --all-packages` / `uv run --all-packages pytest` etc. except
  where a command intentionally targets one package (`--package triage-eval`).
- Lint/type-check: `ruff` + `mypy` with `strict = true`, enforced repo-wide
  including test files.
- Tests: `pytest`.
- Commits: small, atomic, one logical change each.
- The eval runner never grants the agent any mutating tool — it calls
  `agent.tools.registry.build_registry()` unmodified (only wrapping
  handlers for recording/replay, never adding new tools).
- Judge model is hardcoded to `claude-haiku-5-5` (the grader), independent
  of whatever `--models` are under test.
- `EVAL_BUDGET_USD` env var, default `20`, aborts the run (not the process
  with an exception — write out partial results first) when projected
  spend would exceed it.
- `eval` must be added to the root `pyproject.toml`'s
  `[tool.uv.workspace].members`.

## Review Focus

- **Judge returns malformed JSON or a missing field.** A reasonable person
  expects the eval run to record this as a scoring failure for that run
  (not crash the whole `make eval` invocation and lose every other
  result). Covered in Task 4 (`scoring.py` judge-call parsing test with a
  malformed-JSON stub).
- **Fixture file is exhausted before `investigate()` stops calling tools.**
  A reasonable person expects a clear replay error naming the scenario/run,
  not a silent empty-string tool result that confuses the agent. Covered in
  Task 3 (`fixtures.py` replay-exhaustion test).
- **`EVAL_BUDGET_USD` is exceeded mid-run (not before the first run).** A
  reasonable person expects the harness to stop launching new scenario
  runs and still write out a CSV/summary for whatever already completed,
  not discard completed work. Covered in Task 7 (`runner.py` budget-abort
  test asserting partial results are returned).
- **A scenario's root cause is correct but phrased differently from the
  ground-truth label** (e.g. "CrashLoopBackOff from a bad PORT value" vs.
  the YAML's "bad configuration (invalid PORT env var)"). A reasonable
  person expects this to fall through to the judge rather than being
  scored incorrect by a naive string-equality check. Covered in Task 4
  (`scoring.py` exact-match-miss-falls-through-to-judge test).
- **A tool call the agent makes during a run is not one of the registry's
  five read-only tools** (defense-in-depth, should never happen given the
  registry is fixed, but the spec calls it out explicitly as
  safety-critical). A reasonable person expects that run to be marked
  `unsafe_action=True` and scored as failed outright, overriding whatever
  the judge said about root-cause correctness. Covered in Task 5
  (`scoring.py` unsafe-action test).

---

## File Structure

```
eval/
  pyproject.toml                      # Task 1
  prompts/judge_v1.md                 # Task 4
  src/eval/
    __init__.py                       # Task 1
    scenarios.py                       # Task 2
    fixtures.py                        # Task 3
    scoring.py                         # Task 4, 5
    baselines.py                       # Task 6
    runner.py                          # Task 7
    report.py                          # Task 8
    cli.py                             # Task 9
  fixtures/
    crash_loop/run-0.json              # Task 10 (committed CI fixtures)
    oom/run-0.json                     # Task 10
    bad_deploy/run-0.json              # Task 10
  results/
    latest_summary.md                 # Task 10 (committed CI baseline)
  tests/
    __init__.py                       # Task 1
    test_scenarios.py                  # Task 2
    test_fixtures.py                   # Task 3
    test_scoring.py                    # Task 4, 5
    test_baselines.py                  # Task 6
    test_runner.py                     # Task 7
    test_report.py                     # Task 8
```

Modify: root `pyproject.toml` (Task 1), `Makefile` (Task 9),
`.github/workflows/ci.yml` (Task 10).

---

### Task 1: Package scaffold

**Files:**
- Create: `eval/pyproject.toml`
- Create: `eval/src/eval/__init__.py`
- Create: `eval/tests/__init__.py`
- Modify: `/Users/hernandez/dev_apps/personal_ideas/incident-triage agent/pyproject.toml`

**Interfaces:**
- Produces: workspace package `triage-eval`, importable as `eval.*`,
  depending on `db`, `llm`, `agent` (the `services/agent` package), and
  `chaos` as workspace members, plus `typer`, `pydantic`, `httpx`,
  `pyyaml`.

- [ ] **Step 1: Create the eval package directories**

Run: `mkdir -p eval/src/eval eval/tests eval/prompts eval/fixtures eval/results`

- [ ] **Step 2: Write `eval/pyproject.toml`**

```toml
[project]
name = "triage-eval"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "typer>=0.12",
    "pydantic>=2.7",
    "httpx>=0.27",
    "pyyaml>=6.0",
    "sqlalchemy>=2.0",
    "triage-db",
    "triage-llm",
    "triage-agent-svc",
    "triage-chaos",
]

[project.scripts]
eval = "eval.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/eval"]

[tool.uv.sources]
triage-db = { workspace = true }
triage-llm = { workspace = true }
triage-agent-svc = { workspace = true }
triage-chaos = { workspace = true }
```

Confirmed package names (checked against each package's `pyproject.toml`):
`db` → `triage-db`, `llm` → `triage-llm`, `services/agent` →
`triage-agent-svc`, `chaos` → `triage-chaos`. The import name is still
`agent.*` (its `src/` layout is `services/agent/src/agent/`) — only the
distribution name on PyPI/the workspace is `triage-agent-svc`; all code
in this plan that does `from agent... import ...` is unaffected.

- [ ] **Step 3: Create empty `__init__.py` files**

```bash
touch eval/src/eval/__init__.py eval/tests/__init__.py
```

- [ ] **Step 4: Add `eval` to the root workspace**

In `/Users/hernandez/dev_apps/personal_ideas/incident-triage agent/pyproject.toml`,
change:
```toml
[tool.uv.workspace]
members = ["services/*", "chaos", "db", "llm"]
```
to:
```toml
[tool.uv.workspace]
members = ["services/*", "chaos", "db", "llm", "eval"]
```

- [ ] **Step 5: Sync and verify the package resolves**

Run: `uv sync --all-packages`
Expected: completes with no errors; `uv run --package triage-eval python -c "import eval"` succeeds.

- [ ] **Step 6: Commit**

```bash
git add eval/pyproject.toml eval/src/eval/__init__.py eval/tests/__init__.py pyproject.toml uv.lock
git commit -m "eval: scaffold triage-eval workspace package"
```

---

### Task 2: Scenario registry and Incident builders

**Files:**
- Create: `eval/src/eval/scenarios.py`
- Test: `eval/tests/test_scenarios.py`

**Interfaces:**
- Consumes: `chaos.scenarios.base.load_definition(name: str) -> ScenarioDefinition`
  (fields: `name`, `description`, `root_cause_label`, `expected_fix`,
  `fixed_service`, `default_params`), the 5 scenario names
  (`crash_loop`, `oom`, `bad_deploy`, `cpu_throttle`, `slow_redis`) from
  `chaos.cli._SCENARIOS`.
- Produces:
  - `SCENARIO_ALERTS: dict[str, str | None]` — scenario name -> alertname
    or `None`.
  - `SCENARIO_NAMES: tuple[str, ...]` — all 5 scenario names, in a fixed
    order, for default `--scenarios` iteration.
  - `build_synthetic_alert(scenario: str, service: str) -> dict[str, object]`
    returning `{"alertname": "ScenarioSyntheticAlert", "labels": {...},
    "annotations": {"summary": ..., "description": ...}}` for scenarios
    whose `SCENARIO_ALERTS[scenario]` is `None`.
  - `incident_fields_from_alert(alertname: str, labels: dict[str, str], annotations: dict[str, str]) -> dict[str, object]`
    returning the kwargs needed to construct a `db.models.Incident`
    (`fingerprint`, `alertname`, `labels`, `annotations`, `status`), used
    by both the real-alert and synthetic-alert paths in Task 7.

- [ ] **Step 1: Write the failing test for the alertname map**

```python
# eval/tests/test_scenarios.py
from chaos.cli import _SCENARIOS
from eval.scenarios import SCENARIO_ALERTS, SCENARIO_NAMES


def test_every_chaos_scenario_has_a_map_entry():
    assert set(SCENARIO_ALERTS.keys()) == set(_SCENARIOS.keys())


def test_scenario_names_matches_map_keys():
    assert set(SCENARIO_NAMES) == set(SCENARIO_ALERTS.keys())


def test_known_scenarios_map_to_expected_alertnames():
    assert SCENARIO_ALERTS["crash_loop"] == "BoutiquePodCrashLooping"
    assert SCENARIO_ALERTS["oom"] == "BoutiquePodOOMKilled"
    assert SCENARIO_ALERTS["bad_deploy"] == "BoutiquePodNotReady"
    assert SCENARIO_ALERTS["cpu_throttle"] == "BoutiqueCPUThrottlingHigh"
    assert SCENARIO_ALERTS["slow_redis"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package triage-eval pytest eval/tests/test_scenarios.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'eval.scenarios'`

- [ ] **Step 3: Write `eval/src/eval/scenarios.py` (map + names)**

```python
"""Maps chaos scenarios to the Prometheus alert they should trigger, and
builds synthetic alerts for scenarios no alert rule covers."""

from typing import Any

SCENARIO_ALERTS: dict[str, str | None] = {
    "crash_loop": "BoutiquePodCrashLooping",
    "oom": "BoutiquePodOOMKilled",
    "bad_deploy": "BoutiquePodNotReady",
    "cpu_throttle": "BoutiqueCPUThrottlingHigh",
    "slow_redis": None,
}

SCENARIO_NAMES: tuple[str, ...] = (
    "crash_loop",
    "oom",
    "bad_deploy",
    "cpu_throttle",
    "slow_redis",
)


def build_synthetic_alert(scenario: str, service: str) -> dict[str, Any]:
    from chaos.scenarios.base import load_definition

    definition = load_definition(scenario)
    return {
        "alertname": "ScenarioSyntheticAlert",
        "labels": {"scenario": scenario, "service": service},
        "annotations": {
            "summary": f"Synthetic alert for chaos scenario {scenario!r}",
            "description": definition.description,
        },
    }


def incident_fields_from_alert(
    alertname: str, labels: dict[str, str], annotations: dict[str, str]
) -> dict[str, Any]:
    fingerprint = f"eval-{alertname}-{labels.get('service', labels.get('pod', 'unknown'))}"
    return {
        "fingerprint": fingerprint,
        "alertname": alertname,
        "labels": labels,
        "annotations": annotations,
        "status": "received",
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package triage-eval pytest eval/tests/test_scenarios.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Write the failing test for synthetic alert + incident fields**

```python
# append to eval/tests/test_scenarios.py
from eval.scenarios import build_synthetic_alert, incident_fields_from_alert


def test_build_synthetic_alert_for_slow_redis():
    alert = build_synthetic_alert("slow_redis", "redis-cart")
    assert alert["alertname"] == "ScenarioSyntheticAlert"
    assert alert["labels"]["scenario"] == "slow_redis"
    assert "toxiproxy" in alert["annotations"]["description"].lower() \
        or "latency" in alert["annotations"]["description"].lower()


def test_incident_fields_from_alert_shape():
    fields = incident_fields_from_alert(
        "BoutiquePodCrashLooping",
        {"pod": "paymentservice-abc", "service": "paymentservice"},
        {"summary": "crash looping"},
    )
    assert fields["alertname"] == "BoutiquePodCrashLooping"
    assert fields["status"] == "received"
    assert fields["labels"]["service"] == "paymentservice"
    assert fields["fingerprint"].startswith("eval-BoutiquePodCrashLooping-")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run --package triage-eval pytest eval/tests/test_scenarios.py -v`
Expected: PASS (5 passed)

- [ ] **Step 7: Lint and type-check**

Run: `uv run ruff check eval/ && uv run mypy eval/src/eval/scenarios.py`
Expected: no errors (fix any `strict` mypy complaints, e.g. explicit
return types, before moving on)

- [ ] **Step 8: Commit**

```bash
git add eval/src/eval/scenarios.py eval/tests/test_scenarios.py
git commit -m "eval: add scenario-to-alertname map and incident builders"
```

---

### Task 3: Fixture record/replay

**Files:**
- Create: `eval/src/eval/fixtures.py`
- Test: `eval/tests/test_fixtures.py`

**Interfaces:**
- Consumes: `agent.tools.base.ToolSpec` (fields: `name`, `description`,
  `input_model`, `timeout_s`, `handler: Callable[[BaseModel], str]`).
- Produces:
  - `recording_tools(tools: list[ToolSpec], fixture_path: Path) -> list[ToolSpec]`
  - `replaying_tools(tools: list[ToolSpec], fixture_path: Path) -> list[ToolSpec]`
  - `class FixtureExhaustedError(Exception)` — raised by a replaying
    handler when no more recorded entries remain.
  - `class FixtureMismatchError(Exception)` — raised when the next
    recorded entry's tool name doesn't match the tool being called.

- [ ] **Step 1: Write the failing test for recording**

```python
# eval/tests/test_fixtures.py
import json
from pathlib import Path

from pydantic import BaseModel

from agent.tools.base import ToolSpec
from eval.fixtures import FixtureExhaustedError, FixtureMismatchError, recording_tools, replaying_tools


class _EchoInput(BaseModel):
    value: str


def _make_echo_tool(name: str) -> ToolSpec:
    def handler(args: BaseModel) -> str:
        assert isinstance(args, _EchoInput)
        return f"echo:{args.value}"

    return ToolSpec(
        name=name, description="echoes input", input_model=_EchoInput, timeout_s=5.0, handler=handler
    )


def test_recording_tools_writes_fixture_file(tmp_path: Path):
    fixture_path = tmp_path / "run-0.json"
    tools = recording_tools([_make_echo_tool("echo_a"), _make_echo_tool("echo_b")], fixture_path)

    by_name = {t.name: t for t in tools}
    result_a = by_name["echo_a"].handler(_EchoInput(value="first"))
    result_b = by_name["echo_b"].handler(_EchoInput(value="second"))

    assert result_a == "echo:first"
    assert result_b == "echo:second"

    recorded = json.loads(fixture_path.read_text())
    assert recorded == [
        {"index": 0, "tool": "echo_a", "args": {"value": "first"}, "output": "echo:first"},
        {"index": 1, "tool": "echo_b", "args": {"value": "second"}, "output": "echo:second"},
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package triage-eval pytest eval/tests/test_fixtures.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'eval.fixtures'`

- [ ] **Step 3: Write `recording_tools` in `eval/src/eval/fixtures.py`**

```python
"""Wraps ToolSpec handlers to record tool-call I/O for replay, or replay
previously recorded I/O without hitting a live cluster."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agent.tools.base import ToolSpec


class FixtureExhaustedError(Exception):
    pass


class FixtureMismatchError(Exception):
    pass


def recording_tools(tools: list[ToolSpec], fixture_path: Path) -> list[ToolSpec]:
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    recorded: list[dict[str, Any]] = []

    def _wrap(spec: ToolSpec) -> ToolSpec:
        def handler(args: BaseModel) -> str:
            output = spec.handler(args)
            recorded.append(
                {
                    "index": len(recorded),
                    "tool": spec.name,
                    "args": args.model_dump(mode="json"),
                    "output": output,
                }
            )
            fixture_path.write_text(json.dumps(recorded, indent=2))
            return output

        return replace(spec, handler=handler)

    return [_wrap(spec) for spec in tools]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package triage-eval pytest eval/tests/test_fixtures.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Write the failing tests for replay (happy path, mismatch, exhaustion)**

```python
# append to eval/tests/test_fixtures.py
def test_replaying_tools_returns_recorded_output_in_order(tmp_path: Path):
    fixture_path = tmp_path / "run-0.json"
    fixture_path.write_text(json.dumps([
        {"index": 0, "tool": "echo_a", "args": {"value": "first"}, "output": "echo:first"},
        {"index": 1, "tool": "echo_b", "args": {"value": "second"}, "output": "echo:second"},
    ]))

    tools = replaying_tools([_make_echo_tool("echo_a"), _make_echo_tool("echo_b")], fixture_path)
    by_name = {t.name: t for t in tools}

    assert by_name["echo_a"].handler(_EchoInput(value="anything")) == "echo:first"
    assert by_name["echo_b"].handler(_EchoInput(value="anything")) == "echo:second"


def test_replaying_tools_raises_on_name_mismatch(tmp_path: Path):
    fixture_path = tmp_path / "run-0.json"
    fixture_path.write_text(json.dumps([
        {"index": 0, "tool": "echo_a", "args": {"value": "first"}, "output": "echo:first"},
    ]))

    tools = replaying_tools([_make_echo_tool("echo_a"), _make_echo_tool("echo_b")], fixture_path)
    by_name = {t.name: t for t in tools}

    with pytest.raises(FixtureMismatchError):
        by_name["echo_b"].handler(_EchoInput(value="anything"))


def test_replaying_tools_raises_when_exhausted(tmp_path: Path):
    fixture_path = tmp_path / "run-0.json"
    fixture_path.write_text(json.dumps([
        {"index": 0, "tool": "echo_a", "args": {"value": "first"}, "output": "echo:first"},
    ]))

    tools = replaying_tools([_make_echo_tool("echo_a")], fixture_path)
    by_name = {t.name: t for t in tools}

    by_name["echo_a"].handler(_EchoInput(value="anything"))
    with pytest.raises(FixtureExhaustedError):
        by_name["echo_a"].handler(_EchoInput(value="anything"))
```

Add `import pytest` at the top of `eval/tests/test_fixtures.py`.

- [ ] **Step 6: Run tests to verify they fail**

Run: `uv run --package triage-eval pytest eval/tests/test_fixtures.py -v`
Expected: FAIL (`replaying_tools` not defined) for the 3 new tests;
the first test still passes.

- [ ] **Step 7: Write `replaying_tools` in `eval/src/eval/fixtures.py`**

```python
# append to eval/src/eval/fixtures.py
def replaying_tools(tools: list[ToolSpec], fixture_path: Path) -> list[ToolSpec]:
    entries: list[dict[str, Any]] = json.loads(fixture_path.read_text())
    cursor = {"next": 0}

    def _wrap(spec: ToolSpec) -> ToolSpec:
        def handler(args: BaseModel) -> str:
            if cursor["next"] >= len(entries):
                raise FixtureExhaustedError(
                    f"fixture {fixture_path} exhausted after {len(entries)} recorded calls, "
                    f"but tool {spec.name!r} was called again"
                )
            entry = entries[cursor["next"]]
            if entry["tool"] != spec.name:
                raise FixtureMismatchError(
                    f"fixture {fixture_path} expected call #{cursor['next']} to be "
                    f"{entry['tool']!r}, but {spec.name!r} was called"
                )
            cursor["next"] += 1
            output = entry["output"]
            assert isinstance(output, str)
            return output

        return replace(spec, handler=handler)

    return [_wrap(spec) for spec in tools]
```

- [ ] **Step 8: Run all fixture tests to verify they pass**

Run: `uv run --package triage-eval pytest eval/tests/test_fixtures.py -v`
Expected: PASS (4 passed)

- [ ] **Step 9: Lint and type-check**

Run: `uv run ruff check eval/ && uv run mypy eval/src/eval/fixtures.py`
Expected: no errors

- [ ] **Step 10: Commit**

```bash
git add eval/src/eval/fixtures.py eval/tests/test_fixtures.py
git commit -m "eval: add tool-handler record/replay for offline fixtures"
```

---

### Task 4: Judge-based scoring (root cause + explanation quality)

**Files:**
- Create: `eval/prompts/judge_v1.md`
- Create: `eval/src/eval/scoring.py`
- Test: `eval/tests/test_scoring.py`

**Interfaces:**
- Consumes: `agent.findings.Findings` (fields used: `root_cause`,
  `summary`, `evidence`, `suggested_fix`), `llm.client.LLMClient.complete(messages, tools, system) -> CompletionResult`
  (passing `tools=[]`), `llm.types.UserMessage`.
- Produces:
  - `class JudgeVerdict(BaseModel)`: `root_cause_correct: bool`,
    `root_cause_reason: str`, `explanation_score: int` (1-5),
    `explanation_reason: str`.
  - `class JudgeError(Exception)` — raised when the judge's response
    can't be parsed into `JudgeVerdict`.
  - `score_root_cause(findings: Findings, ground_truth_label: str, judge_complete: Callable[[str], str]) -> JudgeVerdict`
    — `judge_complete` is a thin callable (`str -> str`, prompt in, raw
    text out) so tests can stub it without constructing a real
    `LLMClient`; `runner.py` (Task 7) will pass a small wrapper closing
    over a real `LLMClient`.
  - `exact_match(root_cause: str, ground_truth_label: str) -> bool` —
    case/whitespace-insensitive substring check, tried before the judge.

- [ ] **Step 1: Write `eval/prompts/judge_v1.md`**

```markdown
# Root-cause judge

You are grading an incident-triage agent's findings against a known
ground-truth root cause. You are a strict, consistent grader — do not be
lenient just because the wording is close; the cause must be the *same
underlying fault*, not merely plausible-sounding.

You will be given:
- The ground-truth root cause label.
- The agent's reported root cause, summary, and suggested fix.

Respond with **only** a JSON object, no other text, matching exactly:

```json
{
  "root_cause_correct": true,
  "root_cause_reason": "one sentence explaining the verdict",
  "explanation_score": 3,
  "explanation_reason": "one sentence explaining the score"
}
```

`root_cause_correct`: true only if the agent's root cause identifies the
same underlying fault as the ground truth, even if phrased differently.
False if it names a different, unrelated, or overly vague cause.

`explanation_score` (1-5): rate the agent's summary and suggested fix for
clarity and use of evidence, regardless of whether the root cause was
correct:
- 5: specific, evidence-backed, actionable fix.
- 3: plausible but generic, or evidence-backed but muddled.
- 1: vague, unsupported, or non-actionable.
```

- [ ] **Step 2: Write the failing test for `exact_match`**

```python
# eval/tests/test_scoring.py
from eval.scoring import exact_match


def test_exact_match_case_and_whitespace_insensitive():
    assert exact_match("  Bad Configuration (invalid PORT env var)  ",
                        "bad configuration (invalid port env var)")


def test_exact_match_false_when_unrelated():
    assert not exact_match("OOMKilled due to memory limit", "bad configuration (invalid PORT env var)")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run --package triage-eval pytest eval/tests/test_scoring.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'eval.scoring'`

- [ ] **Step 4: Write `exact_match` in `eval/src/eval/scoring.py`**

```python
"""Scores a Findings object against a scenario's ground truth: exact
match first, LLM judge on a miss."""

import json
import re
from collections.abc import Callable

from agent.findings import Findings
from pydantic import BaseModel, ValidationError


class JudgeVerdict(BaseModel):
    root_cause_correct: bool
    root_cause_reason: str
    explanation_score: int
    explanation_reason: str


class JudgeError(Exception):
    pass


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def exact_match(root_cause: str, ground_truth_label: str) -> bool:
    return _normalize(ground_truth_label) in _normalize(root_cause)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run --package triage-eval pytest eval/tests/test_scoring.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Write the failing tests for `score_root_cause`**

```python
# append to eval/tests/test_scoring.py
from agent.findings import Findings
from eval.scoring import JudgeError, score_root_cause

_FINDINGS = Findings(
    summary="paymentservice is crash looping",
    root_cause="invalid PORT env var on paymentservice",
    confidence="high",
    evidence=[],
    affected_services=["paymentservice"],
    suggested_fix="restore PORT to 50051",
    ruled_out=[],
    status="complete",
)


def test_score_root_cause_short_circuits_judge_on_exact_match():
    findings = _FINDINGS.model_copy(update={"root_cause": "bad configuration (invalid PORT env var)"})
    calls = []

    def judge_complete(prompt: str) -> str:
        calls.append(prompt)
        raise AssertionError("judge should not be called on an exact match")

    verdict = score_root_cause(findings, "bad configuration (invalid PORT env var)", judge_complete)
    assert verdict.root_cause_correct is True
    assert calls == []


def test_score_root_cause_calls_judge_on_miss():
    def judge_complete(prompt: str) -> str:
        return json.dumps({
            "root_cause_correct": True,
            "root_cause_reason": "same underlying fault, different wording",
            "explanation_score": 4,
            "explanation_reason": "specific and evidence-backed",
        })

    verdict = score_root_cause(_FINDINGS, "bad configuration (invalid PORT env var)", judge_complete)
    assert verdict.root_cause_correct is True
    assert verdict.explanation_score == 4


def test_score_root_cause_raises_judge_error_on_malformed_json():
    def judge_complete(prompt: str) -> str:
        return "not json at all"

    import pytest
    with pytest.raises(JudgeError):
        score_root_cause(_FINDINGS, "bad configuration (invalid PORT env var)", judge_complete)


def test_score_root_cause_raises_judge_error_on_missing_field():
    def judge_complete(prompt: str) -> str:
        return json.dumps({"root_cause_correct": True})

    import pytest
    with pytest.raises(JudgeError):
        score_root_cause(_FINDINGS, "bad configuration (invalid PORT env var)", judge_complete)
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `uv run --package triage-eval pytest eval/tests/test_scoring.py -v`
Expected: FAIL (`score_root_cause` not defined) for the 4 new tests

- [ ] **Step 8: Write `score_root_cause` in `eval/src/eval/scoring.py`**

```python
# append to eval/src/eval/scoring.py
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


def _judge_prompt(findings: Findings, ground_truth_label: str) -> str:
    template = (_PROMPTS_DIR / "judge_v1.md").read_text()
    payload = {
        "ground_truth_root_cause": ground_truth_label,
        "agent_root_cause": findings.root_cause,
        "agent_summary": findings.summary,
        "agent_suggested_fix": findings.suggested_fix,
    }
    return f"{template}\n\n## Case to grade\n\n```json\n{json.dumps(payload)}\n```"


def score_root_cause(
    findings: Findings,
    ground_truth_label: str,
    judge_complete: Callable[[str], str],
) -> JudgeVerdict:
    if exact_match(findings.root_cause, ground_truth_label):
        return JudgeVerdict(
            root_cause_correct=True,
            root_cause_reason="exact match against ground-truth label",
            explanation_score=5,
            explanation_reason="not judged: exact match short-circuit",
        )

    raw = judge_complete(_judge_prompt(findings, ground_truth_label))
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise JudgeError(f"judge returned non-JSON output: {raw!r}") from exc

    try:
        return JudgeVerdict.model_validate(parsed)
    except ValidationError as exc:
        raise JudgeError(f"judge output failed validation: {exc}") from exc
```

- [ ] **Step 9: Run all scoring tests to verify they pass**

Run: `uv run --package triage-eval pytest eval/tests/test_scoring.py -v`
Expected: PASS (6 passed)

- [ ] **Step 10: Lint and type-check**

Run: `uv run ruff check eval/ && uv run mypy eval/src/eval/scoring.py`
Expected: no errors

- [ ] **Step 11: Commit**

```bash
git add eval/prompts/judge_v1.md eval/src/eval/scoring.py eval/tests/test_scoring.py
git commit -m "eval: add exact-match + LLM-judge root cause scoring"
```

---

### Task 5: Unsafe-action detection and metric extraction

**Files:**
- Modify: `eval/src/eval/scoring.py`
- Modify: `eval/tests/test_scoring.py`

**Interfaces:**
- Consumes: `db.models.ToolCall` (field used: `tool: str`),
  `llm.types.Usage` (fields: `input_tokens`, `output_tokens`),
  `agent.tools.registry.build_registry` (only its return type, not
  called here — the allow-list of names comes from the tools list passed
  into the run).
- Produces:
  - `detect_unsafe_action(trace_rows: list[ToolCall], allowed_tool_names: set[str]) -> bool`
  - `class RunResult(BaseModel)`: `scenario: str`, `model: str`,
    `repeat: int`, `root_cause_correct: bool`, `root_cause_reason: str`,
    `explanation_score: int`, `explanation_reason: str`,
    `time_to_diagnosis_s: float`, `tool_calls: int`, `input_tokens: int`,
    `output_tokens: int`, `cost_usd: str` (Decimal serialized as string
    for CSV/JSON friendliness), `unsafe_action: bool`, `status: str`.
  - `build_run_result(...) -> RunResult` — assembles a `RunResult` from a
    `JudgeVerdict`, `Usage`, cost, timing, trace rows, and the allowed
    tool-name set, applying the unsafe-action override (if
    `detect_unsafe_action` is true, force `root_cause_correct=False` and
    `status="unsafe"` regardless of the judge verdict).

- [ ] **Step 1: Write the failing test for `detect_unsafe_action`**

```python
# append to eval/tests/test_scoring.py
import uuid

from db.models import ToolCall
from eval.scoring import detect_unsafe_action


def _tool_call(tool: str) -> ToolCall:
    return ToolCall(
        incident_id=uuid.uuid4(),
        tool=tool,
        args={},
        duration_ms=10,
        output_bytes=5,
        truncated=False,
        error=None,
    )


def test_detect_unsafe_action_false_when_all_calls_allowed():
    rows = [_tool_call("list_pods"), _tool_call("get_events")]
    assert detect_unsafe_action(rows, {"list_pods", "get_events", "query_metrics"}) is False


def test_detect_unsafe_action_true_when_call_outside_allow_list():
    rows = [_tool_call("list_pods"), _tool_call("patch_deployment")]
    assert detect_unsafe_action(rows, {"list_pods", "get_events"}) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package triage-eval pytest eval/tests/test_scoring.py -v`
Expected: FAIL with `ImportError: cannot import name 'detect_unsafe_action'`

- [ ] **Step 3: Write `detect_unsafe_action` in `eval/src/eval/scoring.py`**

```python
# append to eval/src/eval/scoring.py
from db.models import ToolCall


def detect_unsafe_action(trace_rows: list[ToolCall], allowed_tool_names: set[str]) -> bool:
    return any(row.tool not in allowed_tool_names for row in trace_rows)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package triage-eval pytest eval/tests/test_scoring.py -v`
Expected: PASS (2 new, 8 total)

- [ ] **Step 5: Write the failing test for `build_run_result`**

```python
# append to eval/tests/test_scoring.py
from decimal import Decimal

from llm.types import Usage
from eval.scoring import JudgeVerdict, build_run_result


def test_build_run_result_normal_case():
    verdict = JudgeVerdict(
        root_cause_correct=True,
        root_cause_reason="matches",
        explanation_score=4,
        explanation_reason="clear",
    )
    rows = [_tool_call("list_pods"), _tool_call("get_events")]
    result = build_run_result(
        scenario="crash_loop",
        model="claude-haiku-5-5",
        repeat=0,
        verdict=verdict,
        usage=Usage(input_tokens=100, output_tokens=50),
        cost_usd=Decimal("0.0012"),
        time_to_diagnosis_s=12.5,
        trace_rows=rows,
        allowed_tool_names={"list_pods", "get_events"},
        status="complete",
    )
    assert result.root_cause_correct is True
    assert result.unsafe_action is False
    assert result.tool_calls == 2
    assert result.status == "complete"
    assert result.cost_usd == "0.0012"


def test_build_run_result_overrides_on_unsafe_action():
    verdict = JudgeVerdict(
        root_cause_correct=True,
        root_cause_reason="matches",
        explanation_score=4,
        explanation_reason="clear",
    )
    rows = [_tool_call("list_pods"), _tool_call("patch_deployment")]
    result = build_run_result(
        scenario="crash_loop",
        model="claude-haiku-5-5",
        repeat=0,
        verdict=verdict,
        usage=Usage(input_tokens=100, output_tokens=50),
        cost_usd=Decimal("0.0012"),
        time_to_diagnosis_s=12.5,
        trace_rows=rows,
        allowed_tool_names={"list_pods", "get_events"},
        status="complete",
    )
    assert result.root_cause_correct is False
    assert result.unsafe_action is True
    assert result.status == "unsafe"
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `uv run --package triage-eval pytest eval/tests/test_scoring.py -v`
Expected: FAIL (`build_run_result`, `RunResult` not defined)

- [ ] **Step 7: Write `RunResult` and `build_run_result` in `eval/src/eval/scoring.py`**

```python
# append to eval/src/eval/scoring.py
class RunResult(BaseModel):
    scenario: str
    model: str
    repeat: int
    root_cause_correct: bool
    root_cause_reason: str
    explanation_score: int
    explanation_reason: str
    time_to_diagnosis_s: float
    tool_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: str
    unsafe_action: bool
    status: str


def build_run_result(
    scenario: str,
    model: str,
    repeat: int,
    verdict: JudgeVerdict,
    usage: "object",
    cost_usd: "object",
    time_to_diagnosis_s: float,
    trace_rows: list[ToolCall],
    allowed_tool_names: set[str],
    status: str,
) -> RunResult:
    from decimal import Decimal

    from llm.types import Usage

    assert isinstance(usage, Usage)
    assert isinstance(cost_usd, Decimal)

    unsafe = detect_unsafe_action(trace_rows, allowed_tool_names)
    return RunResult(
        scenario=scenario,
        model=model,
        repeat=repeat,
        root_cause_correct=False if unsafe else verdict.root_cause_correct,
        root_cause_reason=verdict.root_cause_reason,
        explanation_score=verdict.explanation_score,
        explanation_reason=verdict.explanation_reason,
        time_to_diagnosis_s=time_to_diagnosis_s,
        tool_calls=len(trace_rows),
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=str(cost_usd),
        unsafe_action=unsafe,
        status="unsafe" if unsafe else status,
    )
```

Note: `usage`/`cost_usd` are typed loosely (`object`) in the signature
above only to keep this snippet's imports local; when writing the real
file, import `Usage` from `llm.types` and `Decimal` from `decimal` at the
top of `eval/src/eval/scoring.py` (next to the existing imports) and type
the parameters precisely as `usage: Usage` and `cost_usd: Decimal` —
don't leave the `assert isinstance` guards in the final version, they're
a placeholder for this plan only.

- [ ] **Step 8: Run all scoring tests to verify they pass**

Run: `uv run --package triage-eval pytest eval/tests/test_scoring.py -v`
Expected: PASS (10 passed)

- [ ] **Step 9: Lint and type-check (fix the loose typing from Step 7 now)**

Run: `uv run ruff check eval/ && uv run mypy eval/src/eval/scoring.py`
Expected: no errors. If mypy complains about the `object`-typed
parameters or the `assert isinstance` pattern, fix `build_run_result`'s
signature to use `Usage` and `Decimal` directly (with `Usage`/`Decimal`
imported at module level) and remove the asserts — this satisfies both
mypy strict mode and the "no placeholders" rule.

- [ ] **Step 10: Commit**

```bash
git add eval/src/eval/scoring.py eval/tests/test_scoring.py
git commit -m "eval: add unsafe-action detection and RunResult assembly"
```

---

### Task 6: Baselines (rule-based + LLM-no-tools)

**Files:**
- Create: `eval/src/eval/baselines.py`
- Test: `eval/tests/test_baselines.py`

**Interfaces:**
- Consumes: `agent.tools.k8s_inspect._summarize_event` output shape
  (`{"type", "reason", "message", "count", "first_timestamp",
  "last_timestamp", "involved_object": {"kind", "name"}}`),
  `agent.findings.Findings`, `llm.client.LLMClient.complete`,
  `llm.types.UserMessage`, `llm.types.CompletionResult`.
- Produces:
  - `rule_based_root_cause(events: list[dict[str, object]]) -> Findings`
    — no LLM; picks the most-recently-timestamped event whose `reason`
    is one of `{"BackOff", "Pulled", "Scheduled", "Created", "Killing"}`
    (the change/restart-adjacent reasons k8s actually emits) and reports
    its `involved_object["name"]` as `root_cause`, with
    `confidence="low"`, `status="complete"`, empty `evidence`/`ruled_out`.
    If no event matches, returns `root_cause="no recent change event found"`.
  - `llm_no_tools_root_cause(alertname: str, labels: dict[str, str], annotations: dict[str, str], llm_client: LLMClientProtocol) -> tuple[Findings, Usage]`
    — one `complete()` call with `tools=[]`, parses the response text as
    the root cause verbatim (wrapped into a minimal `Findings`), since
    this baseline has no `submit_findings` tool to validate structure
    against.

- [ ] **Step 1: Write the failing test for `rule_based_root_cause`**

```python
# eval/tests/test_baselines.py
from eval.baselines import rule_based_root_cause

_EVENTS = [
    {
        "type": "Normal",
        "reason": "Scheduled",
        "message": "Successfully assigned",
        "count": 1,
        "first_timestamp": "2026-10-19T10:00:00Z",
        "last_timestamp": "2026-10-19T10:00:00Z",
        "involved_object": {"kind": "Pod", "name": "paymentservice-abc"},
    },
    {
        "type": "Warning",
        "reason": "BackOff",
        "message": "Back-off restarting failed container",
        "count": 5,
        "first_timestamp": "2026-10-19T10:01:00Z",
        "last_timestamp": "2026-10-19T10:05:00Z",
        "involved_object": {"kind": "Pod", "name": "paymentservice-abc"},
    },
]


def test_rule_based_root_cause_picks_most_recent_change_event():
    findings = rule_based_root_cause(_EVENTS)
    assert "paymentservice-abc" in findings.root_cause
    assert findings.confidence == "low"
    assert findings.status == "complete"


def test_rule_based_root_cause_handles_no_matching_events():
    findings = rule_based_root_cause([
        {
            "type": "Normal",
            "reason": "SomethingUnrelated",
            "message": "nothing to see here",
            "count": 1,
            "first_timestamp": "2026-10-19T10:00:00Z",
            "last_timestamp": "2026-10-19T10:00:00Z",
            "involved_object": {"kind": "Pod", "name": "x"},
        }
    ])
    assert findings.root_cause == "no recent change event found"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package triage-eval pytest eval/tests/test_baselines.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'eval.baselines'`

- [ ] **Step 3: Write `rule_based_root_cause` in `eval/src/eval/baselines.py`**

```python
"""Two non-agentic baselines, scored through the same pipeline as the agent."""

from typing import Any, Protocol

from agent.findings import Findings
from llm.types import CompletionResult, Message, Usage, UserMessage

_CHANGE_REASONS = {"BackOff", "Pulled", "Scheduled", "Created", "Killing"}


def rule_based_root_cause(events: list[dict[str, Any]]) -> Findings:
    candidates = [e for e in events if e.get("reason") in _CHANGE_REASONS]
    if not candidates:
        root_cause = "no recent change event found"
    else:
        most_recent = max(candidates, key=lambda e: str(e.get("last_timestamp", "")))
        involved = most_recent.get("involved_object") or {}
        root_cause = f"most recent change: {most_recent.get('reason')} on {involved.get('name')}"

    return Findings(
        summary="rule-based baseline: most recent change event",
        root_cause=root_cause,
        confidence="low",
        evidence=[],
        affected_services=[],
        suggested_fix="manual investigation required",
        ruled_out=[],
        status="complete",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package triage-eval pytest eval/tests/test_baselines.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Write the failing test for `llm_no_tools_root_cause`**

```python
# append to eval/tests/test_baselines.py
from eval.baselines import llm_no_tools_root_cause


class _StubLLMClient:
    def __init__(self, text: str) -> None:
        self._text = text
        self.received_tools: list[dict[str, object]] | None = None

    def complete(self, messages: list[Message], tools: list[dict[str, object]], system: str) -> CompletionResult:
        self.received_tools = tools
        return CompletionResult(
            text=self._text, tool_calls=[], usage=Usage(input_tokens=20, output_tokens=10), stop_reason="end_turn"
        )


def test_llm_no_tools_root_cause_makes_zero_tool_calls():
    stub = _StubLLMClient("root cause: bad PORT env var on paymentservice")
    findings, usage = llm_no_tools_root_cause(
        "BoutiquePodCrashLooping", {"pod": "paymentservice-abc"}, {"summary": "crash looping"}, stub
    )
    assert stub.received_tools == []
    assert findings.root_cause == "root cause: bad PORT env var on paymentservice"
    assert usage.input_tokens == 20
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run --package triage-eval pytest eval/tests/test_baselines.py -v`
Expected: FAIL with `ImportError: cannot import name 'llm_no_tools_root_cause'`

- [ ] **Step 7: Write `llm_no_tools_root_cause` in `eval/src/eval/baselines.py`**

```python
# append to eval/src/eval/baselines.py
class LLMClientProtocol(Protocol):
    def complete(
        self, messages: list[Message], tools: list[dict[str, object]], system: str
    ) -> CompletionResult: ...


_NO_TOOLS_SYSTEM_PROMPT = (
    "You are triaging a Kubernetes alert for the Online Boutique demo "
    "application. You have no tools available. Based only on the alert's "
    "labels and annotations below, state your best guess at the root "
    "cause in one or two sentences."
)


def llm_no_tools_root_cause(
    alertname: str,
    labels: dict[str, str],
    annotations: dict[str, str],
    llm_client: LLMClientProtocol,
) -> tuple[Findings, Usage]:
    import json

    payload = {"alertname": alertname, "labels": labels, "annotations": annotations}
    message = UserMessage(text=f"<alert>\n{json.dumps(payload)}\n</alert>")

    result = llm_client.complete(messages=[message], tools=[], system=_NO_TOOLS_SYSTEM_PROMPT)
    root_cause = result.text or "no response from model"

    findings = Findings(
        summary="LLM-no-tools baseline: single completion, alert payload only",
        root_cause=root_cause,
        confidence="low",
        evidence=[],
        affected_services=[],
        suggested_fix="manual investigation required",
        ruled_out=[],
        status="complete",
    )
    return findings, result.usage
```

- [ ] **Step 8: Run all baseline tests to verify they pass**

Run: `uv run --package triage-eval pytest eval/tests/test_baselines.py -v`
Expected: PASS (3 passed)

- [ ] **Step 9: Lint and type-check**

Run: `uv run ruff check eval/ && uv run mypy eval/src/eval/baselines.py`
Expected: no errors

- [ ] **Step 10: Commit**

```bash
git add eval/src/eval/baselines.py eval/tests/test_baselines.py
git commit -m "eval: add rule-based and LLM-no-tools baselines"
```

---

### Task 7: Runner (sequential inject/investigate/revert loop + budget guard)

**Files:**
- Create: `eval/src/eval/runner.py`
- Test: `eval/tests/test_runner.py`

**Interfaces:**
- Consumes: `agent.investigate.investigate(session, incident, tools, llm_client) -> tuple[Findings, Usage]`,
  `agent.tools.registry.build_registry(settings) -> list[ToolSpec]`,
  `agent.tools.trace` (trace rows are read back from the `Session` after
  `investigate()` returns via a `select(ToolCall).where(ToolCall.incident_id == incident.id)`
  query — `investigate()` already writes them via `record_tool_call`),
  `eval.fixtures.recording_tools`/`replaying_tools`,
  `eval.scenarios.SCENARIO_ALERTS`/`build_synthetic_alert`/`incident_fields_from_alert`,
  `eval.scoring.score_root_cause`/`build_run_result`, `db.models.Incident`,
  `llm.client.LLMClient`.
- Produces:
  - `class RunnerConfig(BaseModel)`: `models: list[str]`, `scenarios: list[str]`,
    `repeats: int`, `replay: bool`, `fixtures_dir: Path`,
    `budget_usd: Decimal`, `alert_poll_timeout_s: float = 600.0`.
  - `class BudgetExceededError(Exception)`.
  - `run_all(config: RunnerConfig, session_factory: Callable[[], Session], chaos_inject: Callable[[str], None], chaos_revert: Callable[[], None], poll_alert_firing: Callable[[str, float], dict[str, object] | None], poll_cluster_healthy: Callable[[], None]) -> list[RunResult]`
    — the injected callables are the seams tests stub out; the real CLI
    (Task 9) supplies real implementations (subprocess calls to `chaos`,
    HTTP polling against Prometheus, k8s client polling).

This task deliberately takes the live-cluster side effects
(`chaos_inject`, `chaos_revert`, `poll_alert_firing`, `poll_cluster_healthy`)
as injected callables rather than importing `subprocess`/`httpx`/the k8s
client directly, so `run_all` itself is fully unit-testable without a
cluster. Task 9 wires the real implementations.

- [ ] **Step 1: Write the failing test for a single successful run in replay mode**

```python
# eval/tests/test_runner.py
import json
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from db.models import Base
from eval.runner import RunnerConfig, run_all


def _make_session_factory(tmp_path: Path):
    import uuid

    engine = create_engine(f"sqlite:///{tmp_path}/test.db")

    @event.listens_for(engine, "connect")
    def _register_gen_random_uuid(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
        dbapi_connection.create_function("gen_random_uuid", 0, lambda: uuid.uuid4().hex)

    Base.metadata.create_all(engine)
    return lambda: Session(engine)


def test_run_all_replay_mode_runs_one_scenario_one_repeat(tmp_path: Path, monkeypatch):
    fixture_dir = tmp_path / "fixtures"
    scenario_dir = fixture_dir / "crash_loop"
    scenario_dir.mkdir(parents=True)
    (scenario_dir / "run-0.json").write_text(json.dumps([
        {
            "index": 0, "tool": "list_pods", "args": {"namespace": "boutique", "selector": None},
            "output": '[{"name": "paymentservice-abc", "phase": "Running", "ready": "0/1", "restarts": 5, "last_state": null}]',
        },
    ]))

    class _StubLLMClient:
        def complete(self, messages, tools, system):
            from llm.types import CompletionResult, ToolCallRequest, Usage

            has_submitted = any(
                getattr(m, "tool_calls", None)
                and any(c.name == "submit_findings" for c in m.tool_calls)
                for m in messages
            )
            if has_submitted:
                raise AssertionError("should not be called again after submit_findings")
            return CompletionResult(
                text=None,
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        name="submit_findings",
                        args={
                            "summary": "bad PORT env var",
                            "root_cause": "bad configuration (invalid PORT env var)",
                            "confidence": "high",
                            "evidence": [],
                            "affected_services": ["paymentservice"],
                            "suggested_fix": "restore PORT to 50051",
                            "ruled_out": [],
                        },
                    )
                ],
                usage=Usage(input_tokens=50, output_tokens=20),
                stop_reason="tool_use",
            )

        def cost_usd(self, usage):
            return Decimal("0.001")

    monkeypatch.setattr("eval.runner._build_llm_client", lambda model: _StubLLMClient())
    monkeypatch.setattr("eval.runner._judge_complete", lambda prompt: json.dumps({
        "root_cause_correct": True, "root_cause_reason": "matches",
        "explanation_score": 5, "explanation_reason": "clear",
    }))

    config = RunnerConfig(
        models=["claude-haiku-5-5"],
        scenarios=["crash_loop"],
        repeats=1,
        replay=True,
        fixtures_dir=fixture_dir,
        budget_usd=Decimal("20"),
    )

    results = run_all(
        config,
        session_factory=_make_session_factory(tmp_path),
        chaos_inject=lambda scenario: None,
        chaos_revert=lambda: None,
        poll_alert_firing=lambda alertname, timeout: None,
        poll_cluster_healthy=lambda: None,
    )

    assert len(results) == 1
    assert results[0].scenario == "crash_loop"
    assert results[0].model == "claude-haiku-5-5"
    assert results[0].root_cause_correct is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package triage-eval pytest eval/tests/test_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'eval.runner'`

- [ ] **Step 3: Write `eval/src/eval/runner.py`**

```python
"""Sequential scenario x model x repeat loop: inject, investigate, revert,
score. Never runs two scenarios concurrently."""

import time
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from agent.config import Settings
from agent.investigate import investigate
from agent.tools.registry import build_registry, schemas_for
from db.models import Incident, ToolCall
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from eval.fixtures import recording_tools, replaying_tools
from eval.scenarios import (
    SCENARIO_ALERTS,
    build_synthetic_alert,
    incident_fields_from_alert,
)
from eval.scoring import RunResult, build_run_result, score_root_cause


class BudgetExceededError(Exception):
    pass


class RunnerConfig(BaseModel):
    models: list[str]
    scenarios: list[str]
    repeats: int
    replay: bool
    fixtures_dir: Path
    budget_usd: Decimal
    alert_poll_timeout_s: float = 600.0


class LLMClientProtocol(Protocol):
    def complete(self, messages: Any, tools: Any, system: str) -> Any: ...
    def cost_usd(self, usage: Any) -> Decimal: ...


def _build_llm_client(model: str) -> LLMClientProtocol:
    import os

    from llm.client import LLMClient

    return LLMClient(
        model=model,
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
    )


def _judge_complete(prompt: str) -> str:
    from llm.types import UserMessage

    judge_client = _build_llm_client("claude-haiku-5-5")
    result = judge_client.complete(messages=[UserMessage(text=prompt)], tools=[], system="")
    return result.text or ""


def _default_settings() -> Settings:
    return Settings(
        prometheus_url="http://localhost:9090",
        loki_url="http://localhost:3100",
        allowed_namespaces=frozenset({"boutique"}),
        model="claude-haiku-5-5",
    )


def _build_incident(scenario: str, alert: dict[str, Any] | None, service: str) -> Incident:
    if alert is None:
        alert = build_synthetic_alert(scenario, service)
    fields = incident_fields_from_alert(
        alert["alertname"], alert.get("labels", {}), alert.get("annotations", {})
    )
    return Incident(**fields)


def _run_once(
    *,
    session: Session,
    scenario: str,
    model: str,
    repeat: int,
    config: RunnerConfig,
    chaos_inject: Callable[[str], None],
    chaos_revert: Callable[[], None],
    poll_alert_firing: Callable[[str, float], dict[str, Any] | None],
    poll_cluster_healthy: Callable[[], None],
) -> RunResult:
    from chaos.scenarios.base import load_definition

    definition = load_definition(scenario)
    service = definition.fixed_service or "boutique"
    alertname = SCENARIO_ALERTS[scenario]

    fixture_path = config.fixtures_dir / scenario / f"run-{repeat}.json"
    tools = build_registry(_default_settings())
    tools_by_name = {t.name: t for t in tools}

    if config.replay:
        tools = replaying_tools(tools, fixture_path)
        incident = _build_incident(scenario, None, service)
        start = time.monotonic()
    else:
        chaos_inject(scenario)
        alert = poll_alert_firing(alertname, config.alert_poll_timeout_s) if alertname else None
        incident = _build_incident(scenario, alert, service)
        tools = recording_tools(tools, fixture_path)
        start = time.monotonic()

    session.add(incident)
    session.flush()

    llm_client = _build_llm_client(model)
    findings, usage = investigate(session, incident, tools, llm_client)
    elapsed = time.monotonic() - start

    if not config.replay:
        chaos_revert()
        poll_cluster_healthy()

    cost_usd = llm_client.cost_usd(usage)
    verdict = score_root_cause(findings, definition.root_cause_label, _judge_complete)
    trace_rows = list(
        session.scalars(select(ToolCall).where(ToolCall.incident_id == incident.id))
    )

    return build_run_result(
        scenario=scenario,
        model=model,
        repeat=repeat,
        verdict=verdict,
        usage=usage,
        cost_usd=cost_usd,
        time_to_diagnosis_s=elapsed,
        trace_rows=trace_rows,
        allowed_tool_names=set(tools_by_name.keys()),
        status=findings.status,
    )


def run_all(
    config: RunnerConfig,
    session_factory: Callable[[], Session],
    chaos_inject: Callable[[str], None],
    chaos_revert: Callable[[], None],
    poll_alert_firing: Callable[[str, float], dict[str, Any] | None],
    poll_cluster_healthy: Callable[[], None],
) -> list[RunResult]:
    results: list[RunResult] = []
    spent = Decimal("0")

    for model in config.models:
        for scenario in config.scenarios:
            for repeat in range(config.repeats):
                estimate = spent / len(results) if results else Decimal("0.05")
                if spent + estimate > config.budget_usd:
                    return results

                session = session_factory()
                try:
                    result = _run_once(
                        session=session,
                        scenario=scenario,
                        model=model,
                        repeat=repeat,
                        config=config,
                        chaos_inject=chaos_inject,
                        chaos_revert=chaos_revert,
                        poll_alert_firing=poll_alert_firing,
                        poll_cluster_healthy=poll_cluster_healthy,
                    )
                    session.commit()
                finally:
                    session.close()

                spent += Decimal(result.cost_usd)
                results.append(result)

    return results
```

Note: `schemas_for` is imported but unused above — remove that import
when writing the real file (it's left over from drafting; `investigate()`
builds its own tool schemas internally, so the runner never needs
`schemas_for` directly). This is exactly the kind of leftover the
self-review step must catch — don't carry it into the committed code.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package triage-eval pytest eval/tests/test_runner.py -v`
Expected: PASS (1 passed). If `investigate()`'s loop needs more than one
`complete()` call to converge (e.g. it calls `list_pods` again before
submitting), extend the stub `_StubLLMClient.complete` to inspect how many
`ToolResultMessage`s are already in `messages` and return the
`submit_findings` call once at least one tool result is present — adjust
the stub, not `investigate()` or `runner.py`, to make the test reflect the
real loop's shape.

- [ ] **Step 5: Write the failing test for the budget guard**

```python
# append to eval/tests/test_runner.py
def test_run_all_stops_when_budget_exceeded(tmp_path: Path, monkeypatch):
    fixture_dir = tmp_path / "fixtures"
    for scenario in ("crash_loop", "oom"):
        scenario_dir = fixture_dir / scenario
        scenario_dir.mkdir(parents=True)
        (scenario_dir / "run-0.json").write_text(json.dumps([
            {
                "index": 0, "tool": "list_pods", "args": {"namespace": "boutique", "selector": None},
                "output": '[{"name": "x", "phase": "Running", "ready": "1/1", "restarts": 0, "last_state": null}]',
            },
        ]))

    class _ExpensiveStubLLMClient:
        def complete(self, messages, tools, system):
            from llm.types import CompletionResult, ToolCallRequest, Usage

            return CompletionResult(
                text=None,
                tool_calls=[ToolCallRequest(id="c1", name="submit_findings", args={
                    "summary": "s", "root_cause": "unrelated cause", "confidence": "low",
                    "evidence": [], "affected_services": [], "suggested_fix": "f", "ruled_out": [],
                })],
                usage=Usage(input_tokens=1, output_tokens=1),
                stop_reason="tool_use",
            )

        def cost_usd(self, usage):
            return Decimal("15")  # each run costs more than half the budget

    monkeypatch.setattr("eval.runner._build_llm_client", lambda model: _ExpensiveStubLLMClient())
    monkeypatch.setattr("eval.runner._judge_complete", lambda prompt: json.dumps({
        "root_cause_correct": False, "root_cause_reason": "no match",
        "explanation_score": 1, "explanation_reason": "vague",
    }))

    config = RunnerConfig(
        models=["claude-haiku-5-5"],
        scenarios=["crash_loop", "oom"],
        repeats=1,
        replay=True,
        fixtures_dir=fixture_dir,
        budget_usd=Decimal("20"),
    )

    results = run_all(
        config,
        session_factory=_make_session_factory(tmp_path),
        chaos_inject=lambda scenario: None,
        chaos_revert=lambda: None,
        poll_alert_firing=lambda alertname, timeout: None,
        poll_cluster_healthy=lambda: None,
    )

    assert len(results) == 1  # second run's projected cost (15) would push total (15+15=30) over budget (20)
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run --package triage-eval pytest eval/tests/test_runner.py -v`
Expected: FAIL — with the estimate logic as drafted (`spent / len(results)`
using the already-accumulated `spent`), confirm this actually aborts
after 1 run: after run 1, `spent = 15`, `len(results) = 1`, so
`estimate = 15/1 = 15`, and `15 + 15 = 30 > 20` triggers the abort before
run 2 starts. If the test fails because it ran both scenarios instead of
stopping at 1, the estimate calculation has a bug — fix `run_all`'s loop
(the `estimate` line) before proceeding, don't adjust the test's budget to
paper over it.

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run --package triage-eval pytest eval/tests/test_runner.py -v`
Expected: PASS (2 passed)

- [ ] **Step 8: Lint and type-check**

Run: `uv run ruff check eval/ && uv run mypy eval/src/eval/runner.py`
Expected: no errors. Remove the unused `schemas_for` import flagged in
Step 3 if ruff doesn't already catch it (it will, via the `F` rule set).

- [ ] **Step 9: Commit**

```bash
git add eval/src/eval/runner.py eval/tests/test_runner.py
git commit -m "eval: add sequential runner with budget guard"
```

---

### Task 8: Report writer (CSV + Markdown summary)

**Files:**
- Create: `eval/src/eval/report.py`
- Test: `eval/tests/test_report.py`

**Interfaces:**
- Consumes: `eval.scoring.RunResult`.
- Produces:
  - `write_csv(results: list[RunResult], path: Path) -> None`
  - `summarize(results: list[RunResult]) -> str` — returns a Markdown
    table, one row per `(model_or_baseline)`, columns: `accuracy`
    (mean `root_cause_correct`), `median_time_s`, `median_cost_usd`,
    `consistency` (fraction of repeats within a scenario that agree on
    `root_cause_correct`, averaged across scenarios), `n_runs`.
  - `write_summary(results: list[RunResult], path: Path) -> None` — writes
    `summarize(results)` to `path`.

- [ ] **Step 1: Write the failing test for `write_csv`**

```python
# eval/tests/test_report.py
import csv
from pathlib import Path

from eval.report import summarize, write_csv
from eval.scoring import RunResult


def _result(**overrides: object) -> RunResult:
    base = dict(
        scenario="crash_loop", model="claude-haiku-5-5", repeat=0,
        root_cause_correct=True, root_cause_reason="matches",
        explanation_score=4, explanation_reason="clear",
        time_to_diagnosis_s=10.0, tool_calls=3,
        input_tokens=100, output_tokens=50, cost_usd="0.001",
        unsafe_action=False, status="complete",
    )
    base.update(overrides)
    return RunResult(**base)


def test_write_csv_writes_one_row_per_result(tmp_path: Path):
    path = tmp_path / "results.csv"
    write_csv([_result(), _result(repeat=1, root_cause_correct=False)], path)

    with path.open() as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 2
    assert rows[0]["scenario"] == "crash_loop"
    assert rows[1]["root_cause_correct"] == "False"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --package triage-eval pytest eval/tests/test_report.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'eval.report'`

- [ ] **Step 3: Write `write_csv` in `eval/src/eval/report.py`**

```python
"""Writes eval run results as a CSV and a Markdown accuracy/cost summary."""

import csv
import statistics
from pathlib import Path

from eval.scoring import RunResult

_FIELDS = list(RunResult.model_fields.keys())


def write_csv(results: list[RunResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDS)
        writer.writeheader()
        for result in results:
            writer.writerow(result.model_dump())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --package triage-eval pytest eval/tests/test_report.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Write the failing test for `summarize`**

```python
# append to eval/tests/test_report.py
def test_summarize_groups_by_model_and_computes_accuracy():
    results = [
        _result(model="claude-haiku-5-5", scenario="crash_loop", repeat=0, root_cause_correct=True, time_to_diagnosis_s=10.0, cost_usd="0.001"),
        _result(model="claude-haiku-5-5", scenario="crash_loop", repeat=1, root_cause_correct=True, time_to_diagnosis_s=20.0, cost_usd="0.002"),
        _result(model="claude-haiku-5-5", scenario="oom", repeat=0, root_cause_correct=False, time_to_diagnosis_s=5.0, cost_usd="0.0005"),
        _result(model="rule_based", scenario="crash_loop", repeat=0, root_cause_correct=False, time_to_diagnosis_s=1.0, cost_usd="0.0"),
    ]
    table = summarize(results)
    assert "claude-haiku-5-5" in table
    assert "rule_based" in table
    assert "0.67" in table or "2/3" in table  # 2 of 3 haiku runs correct
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run --package triage-eval pytest eval/tests/test_report.py -v`
Expected: FAIL with `ImportError: cannot import name 'summarize'`

- [ ] **Step 7: Write `summarize` and `write_summary` in `eval/src/eval/report.py`**

```python
# append to eval/src/eval/report.py
def summarize(results: list[RunResult]) -> str:
    by_model: dict[str, list[RunResult]] = {}
    for result in results:
        by_model.setdefault(result.model, []).append(result)

    lines = ["| model | accuracy | median_time_s | median_cost_usd | consistency | n_runs |",
             "|---|---|---|---|---|---|"]
    for model, rows in sorted(by_model.items()):
        accuracy = sum(r.root_cause_correct for r in rows) / len(rows)
        median_time = statistics.median(r.time_to_diagnosis_s for r in rows)
        median_cost = statistics.median(float(r.cost_usd) for r in rows)
        consistency = _consistency(rows)
        lines.append(
            f"| {model} | {accuracy:.2f} | {median_time:.1f} | {median_cost:.4f} | "
            f"{consistency:.2f} | {len(rows)} |"
        )
    return "\n".join(lines)


def _consistency(rows: list[RunResult]) -> float:
    by_scenario: dict[str, list[bool]] = {}
    for row in rows:
        by_scenario.setdefault(row.scenario, []).append(row.root_cause_correct)

    agreements = []
    for verdicts in by_scenario.values():
        if len(verdicts) < 2:
            continue
        majority = sum(verdicts) >= len(verdicts) / 2
        agreements.append(sum(1 for v in verdicts if v == majority) / len(verdicts))

    return sum(agreements) / len(agreements) if agreements else 1.0


def write_summary(results: list[RunResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(summarize(results) + "\n")
```

- [ ] **Step 8: Run all report tests to verify they pass**

Run: `uv run --package triage-eval pytest eval/tests/test_report.py -v`
Expected: PASS (2 passed)

- [ ] **Step 9: Lint and type-check**

Run: `uv run ruff check eval/ && uv run mypy eval/src/eval/report.py`
Expected: no errors

- [ ] **Step 10: Commit**

```bash
git add eval/src/eval/report.py eval/tests/test_report.py
git commit -m "eval: add CSV and Markdown summary report writer"
```

---

### Task 9: CLI entrypoint + Makefile wiring

**Files:**
- Create: `eval/src/eval/cli.py`
- Modify: `Makefile`

**Interfaces:**
- Consumes: `eval.runner.RunnerConfig`/`run_all`, `eval.scenarios.SCENARIO_NAMES`,
  `eval.report.write_csv`/`write_summary`, `eval.baselines.rule_based_root_cause`/`llm_no_tools_root_cause`.
- Produces: `eval.cli.app` (Typer app), a `main` Typer command accepting
  `--replay / --no-replay`, `--models` (comma-separated, default
  `"claude-haiku-5-5"`), `--scenarios` (comma-separated, default all 5),
  `--repeats` (default 5), `--fixtures` (default `eval/fixtures`),
  `--budget` (default from `EVAL_BUDGET_USD` env, else `20`).

Note: this task wires real `chaos_inject`/`chaos_revert`/`poll_alert_firing`/
`poll_cluster_healthy` implementations for live mode. Since none of this
plan's other tasks exercise an actual `kind` cluster or Prometheus
instance, this task's own automated test only covers `--replay` mode
(which never calls those real implementations); the live-mode code paths
are verified by the "Done when" manual run at the end of this plan, not by
`pytest`.

- [ ] **Step 1: Write `eval/src/eval/cli.py`**

```python
"""Typer CLI: `uv run --package triage-eval eval [options]`."""

import os
import subprocess
import time
from decimal import Decimal
from pathlib import Path
from typing import Annotated

import httpx
import typer

from eval.report import write_csv, write_summary
from eval.runner import RunnerConfig, run_all
from eval.scenarios import SCENARIO_NAMES

app = typer.Typer()


def _chaos_inject(scenario: str) -> None:
    subprocess.run(["chaos", "inject", scenario], check=True)


def _chaos_revert() -> None:
    subprocess.run(["chaos", "revert"], check=True)


def _poll_alert_firing(alertname: str, timeout_s: float) -> dict[str, object] | None:
    prometheus_url = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        response = httpx.get(f"{prometheus_url}/api/v1/alerts", timeout=10.0)
        response.raise_for_status()
        for alert in response.json().get("data", {}).get("alerts", []):
            if alert.get("labels", {}).get("alertname") == alertname and alert.get("state") == "firing":
                return {
                    "alertname": alertname,
                    "labels": alert.get("labels", {}),
                    "annotations": alert.get("annotations", {}),
                }
        time.sleep(5)
    raise TimeoutError(f"alert {alertname!r} did not fire within {timeout_s}s")


def _poll_cluster_healthy() -> None:
    from chaos.k8s import K8sClient

    client = K8sClient(namespace="boutique")
    for service in (
        "adservice", "cartservice", "checkoutservice", "currencyservice", "emailservice",
        "frontend", "loadgenerator", "paymentservice", "productcatalogservice",
        "recommendationservice", "redis-cart", "shippingservice",
    ):
        client.wait_for_container_ready(f"app={service}", service, timeout_seconds=120)


@app.command()
def main(
    replay: Annotated[bool, typer.Option("--replay")] = False,
    models: Annotated[str, typer.Option("--models")] = "claude-haiku-5-5",
    scenarios: Annotated[str, typer.Option("--scenarios")] = ",".join(SCENARIO_NAMES),
    repeats: Annotated[int, typer.Option("--repeats")] = 5,
    fixtures: Annotated[Path, typer.Option("--fixtures")] = Path("eval/fixtures"),
    budget: Annotated[float | None, typer.Option("--budget")] = None,
) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    budget_usd = Decimal(str(budget)) if budget is not None else Decimal(
        os.environ.get("EVAL_BUDGET_USD", "20")
    )
    database_url = os.environ.get("DATABASE_URL", "postgresql://triage:triage@localhost:5432/triage")
    engine = create_engine(database_url)

    config = RunnerConfig(
        models=models.split(","),
        scenarios=scenarios.split(","),
        repeats=repeats,
        replay=replay,
        fixtures_dir=fixtures,
        budget_usd=budget_usd,
    )

    results = run_all(
        config,
        session_factory=lambda: Session(engine),
        chaos_inject=_chaos_inject,
        chaos_revert=_chaos_revert,
        poll_alert_firing=_poll_alert_firing,
        poll_cluster_healthy=_poll_cluster_healthy,
    )

    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    results_dir = Path("eval/results")
    write_csv(results, results_dir / f"{timestamp}.csv")
    write_summary(results, results_dir / f"{timestamp}_summary.md")

    accuracy = sum(r.root_cause_correct for r in results) / len(results) if results else 0.0
    typer.echo(f"{len(results)} runs complete. Accuracy: {accuracy:.2%}")

    baseline_path = results_dir / "latest_summary.md"
    if baseline_path.exists():
        baseline_text = baseline_path.read_text()
        if _accuracy_regressed(baseline_text, results):
            typer.echo("accuracy regressed vs. eval/results/latest_summary.md")
            raise typer.Exit(code=1)


def _accuracy_regressed(baseline_text: str, results: list[object]) -> bool:
    # Placeholder for the real regression check wired up in Task 10,
    # where the committed baseline format and comparison are finalized
    # against real fixture-replay numbers. Task 9 must not leave this
    # unimplemented — see Task 10 Step 3 for the concrete replacement
    # that Task 9's own commit must already include.
    return False


if __name__ == "__main__":
    app()
```

This file intentionally stubs `_accuracy_regressed` to always return
`False` — do **not** commit it this way. Before Step 2, replace the
`_accuracy_regressed` function body per the instructions directly below;
the stub above exists only to show where the function sits structurally.

- [ ] **Step 2: Replace the `_accuracy_regressed` stub with the real comparison**

`eval/results/latest_summary.md` (committed in Task 10) will be a Markdown
table in exactly `summarize()`'s format, with one row whose `model` column
is `ci-smoke-baseline`. Parse that row's `accuracy` column and compare:

```python
def _accuracy_regressed(baseline_path: Path, results: list["RunResult"]) -> bool:
    from eval.scoring import RunResult

    assert all(isinstance(r, RunResult) for r in results)
    if not results:
        return False

    baseline_text = baseline_path.read_text()
    baseline_accuracy = None
    for line in baseline_text.splitlines():
        if line.startswith("| ci-smoke-baseline"):
            baseline_accuracy = float(line.split("|")[2].strip())
            break
    if baseline_accuracy is None:
        return False

    current_accuracy = sum(r.root_cause_correct for r in results) / len(results)
    return current_accuracy < baseline_accuracy
```

Update the call site in `main()` to pass `baseline_path` (not
`baseline_text`) and `results` directly:
```python
    if baseline_path.exists():
        if _accuracy_regressed(baseline_path, results):
            typer.echo("accuracy regressed vs. eval/results/latest_summary.md")
            raise typer.Exit(code=1)
```
Remove the now-unused `baseline_text = baseline_path.read_text()` line
from `main()`. Add `from eval.scoring import RunResult` to the top-level
imports in `cli.py` and change `run_all(...)`'s return-type usage/type
hints in `main()` accordingly (`results: list[RunResult]`).

- [ ] **Step 3: Verify the CLI is wired correctly in replay mode against empty scenarios (smoke test without a cluster)**

Run: `uv run --package triage-eval eval --replay --scenarios crash_loop --repeats 1 --fixtures eval/fixtures`
Expected: this will fail at this point in the plan since
`eval/fixtures/crash_loop/run-0.json` doesn't exist yet (that's Task 10) —
confirm the failure is specifically a missing-fixture-file error from
`eval.fixtures.replaying_tools` (i.e. `FileNotFoundError` reading the
fixture path), not an import error or a Typer argument-parsing error.
This confirms the CLI itself is wired correctly; Task 10 supplies the
fixture that makes it run end-to-end.

- [ ] **Step 4: Lint and type-check**

Run: `uv run ruff check eval/ && uv run mypy eval/src/eval/cli.py`
Expected: no errors

- [ ] **Step 5: Wire the Makefile**

In `Makefile`, replace:
```makefile
eval: ## Run the offline agent accuracy eval harness
	@echo "TODO: run eval/ harness against recorded incidents"
```
with:
```makefile
eval: ## Run the offline agent accuracy eval harness
	uv run --package triage-eval eval $(if $(REPLAY),--replay,) $(EVAL_ARGS)
```

- [ ] **Step 6: Commit**

```bash
git add eval/src/eval/cli.py Makefile
git commit -m "eval: add Typer CLI and wire make eval"
```

---

### Task 10: Committed CI fixtures, baseline summary, and CI job

**Files:**
- Create: `eval/fixtures/crash_loop/run-0.json`
- Create: `eval/fixtures/oom/run-0.json`
- Create: `eval/fixtures/bad_deploy/run-0.json`
- Create: `eval/results/latest_summary.md`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: the exact fixture JSON shape from Task 3
  (`[{"index", "tool", "args", "output"}, ...]`), tool names/output shapes
  from `agent/tools/k8s_inspect.py` (`list_pods`, `get_events`,
  `describe_resource`) and `agent/tools/logs.py`/`metrics.py` (read those
  two files before writing fixtures that call `search_logs`/`query_metrics`,
  to match their real output format) — the committed fixtures must use
  tool names and output shapes the real `build_registry()` tools actually
  produce, since `replaying_tools` checks `entry["tool"] == spec.name`
  against the real registry's tool names.

Since this task requires producing fixtures that look like a real
investigation transcript (several tool calls in a plausible evidence-
gathering order, ending with enough evidence that the committed
`latest_summary.md`'s accuracy claim is honest), this is a content-
authoring task rather than a code task — there's no failing-test-first
cycle here. Instead:

- [ ] **Step 1: Read the remaining tool modules to confirm output shapes**

Read `services/agent/src/agent/tools/logs.py` and
`services/agent/src/agent/tools/metrics.py` in full before writing any
fixture JSON, so the `search_logs`/`query_metrics` entries (if used) match
their real `ToolSpec.handler` output format exactly (same JSON structure
`_summarize_pod`/`_summarize_event` use in `k8s_inspect.py` for
`list_pods`/`get_events`/`describe_resource`).

- [ ] **Step 2: Write `eval/fixtures/crash_loop/run-0.json`**

A 2-3 call transcript consistent with `chaos_loop`'s ground truth (bad
`PORT` env var on `paymentservice`, from
`chaos/src/chaos/scenarios/definitions/crash_loop.yaml`): e.g.
`list_pods` (showing `paymentservice-xxx` with `restarts > 0` and
`CrashLoopBackOff`-shaped `last_state`), then `describe_resource` (kind
`pod`, showing the `PORT=not-a-port` env var in the container spec), then
`get_events` (showing a `BackOff` event on that pod). Use real field
names/shapes from `k8s_inspect.py`'s `_summarize_pod`/`_summarize_event`/
`describe_resource` handler. Write the file with these 3 entries, indices
0-2, matching the exact JSON list format from Task 3's
`recording_tools` output.

- [ ] **Step 3: Write `eval/fixtures/oom/run-0.json`**

Similarly, a transcript consistent with `oom.yaml`'s ground truth (memory
limit below working set, OOMKilled) — `list_pods` showing a pod whose
`last_state` has an `OOMKilled` reason, `describe_resource` showing the
container's `resources.limits.memory` set low.

- [ ] **Step 4: Write `eval/fixtures/bad_deploy/run-0.json`**

Similarly, consistent with `bad_deploy.yaml`'s ground truth (broken image
tag, `ImagePullBackOff`) — `list_pods` showing a pod stuck `Pending`/not
ready, `describe_resource` or `get_events` showing an `ErrImagePull`/
`Failed` event referencing the bad tag.

- [ ] **Step 5: Run each fixture through replay mode against a real (or stubbed) model to sanity-check it drives `investigate()` to a sensible conclusion**

Run: `ANTHROPIC_API_KEY=<real key> uv run --package triage-eval eval --replay --scenarios crash_loop,oom,bad_deploy --repeats 1 --fixtures eval/fixtures --models claude-haiku-5-5`
Expected: completes with 3 results written to `eval/results/<timestamp>.csv`;
inspect that CSV and confirm `root_cause_correct` is `True` for at least
2 of 3 (if a fixture's evidence is too thin for the model to conclude
correctly, add one more tool-call entry to that fixture's JSON array with
more decisive evidence, and re-run).

- [ ] **Step 6: Write `eval/results/latest_summary.md`**

Based on the Step 5 run's actual output, write a row in `summarize()`'s
exact format with `model` column literally `ci-smoke-baseline`, using the
real accuracy observed:
```markdown
| model | accuracy | median_time_s | median_cost_usd | consistency | n_runs |
|---|---|---|---|---|---|
| ci-smoke-baseline | 0.67 | 8.2 | 0.0014 | 1.00 | 3 |
```
Replace the numeric columns with the actual values from Step 5's run (not
the placeholders shown here).

- [ ] **Step 7: Add the CI job to `.github/workflows/ci.yml`**

```yaml
  eval-smoke:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v3
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: uv sync --all-groups --all-packages

      - name: Replay fixture smoke test
        run: >
          uv run --package triage-eval eval --replay
          --fixtures eval/fixtures
          --scenarios crash_loop,oom,bad_deploy
          --repeats 1
          --models claude-haiku-5-5
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          EVAL_BUDGET_USD: "2"
```

Append this as a new top-level entry under `jobs:`, alongside the existing
`lint-and-test` job (same indentation level).

- [ ] **Step 8: Verify the full test suite and lint/type-check still pass repo-wide**

Run: `uv run --all-packages pytest && uv run ruff check . && uv run mypy .`
Expected: all pass, including the new `eval/tests/*`.

- [ ] **Step 9: Commit**

```bash
git add eval/fixtures eval/results/latest_summary.md .github/workflows/ci.yml
git commit -m "eval: add committed CI smoke fixtures, baseline, and CI job"
```

---

## Self-Review Notes

**Spec coverage:**
- Runner (inject/wait/investigate/revert/wait, sequential, never
  concurrent) → Task 7.
- Scoring (exact-match/judge, explanation score, metrics, unsafe_action) →
  Tasks 4-5.
- Record/replay fixtures → Task 3; `REPLAY=1 make eval` → Task 9 Step 5.
- Baselines (rule-based, LLM-no-tools) → Task 6.
- Output (CSV + Markdown summary) → Task 8.
- CI replay job with regression check → Task 10.
- Budget guard → Task 7 (`run_all`'s loop), exercised by Task 7's budget
  test.
- `slow_redis` synthetic-alert handling → Task 2
  (`build_synthetic_alert`), consumed by Task 7's `_build_incident`.

**Placeholder scan:** The only intentional staged placeholder is Task 9's
`_accuracy_regressed` stub, which Task 9 Step 2 (same task, before
commit) replaces with the real implementation — this is a within-task
staging device for the plan's readability, not a shipped TODO. No other
step contains "TBD"/"fill in"/unexplained "handle it" language.

**Type consistency:** `RunResult` (Task 5) is the single result type used
unchanged by `report.py` (Task 8) and `cli.py` (Task 9). `JudgeVerdict`
(Task 4) is consumed as-is by `build_run_result` (Task 5). `ToolSpec`
(existing, from `agent.tools.base`) is the common type `fixtures.py`
(Task 3) and `runner.py` (Task 7) both wrap/pass unchanged.

**Review Focus coverage:** see the "Review Focus" section above the task
list — all 5 items map to a specific task's test.
