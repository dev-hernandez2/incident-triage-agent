# chaos CLI — Design Spec

Date: 2026-10-13

## Purpose

A Python CLI (`chaos`) that injects and reverts fault scenarios against the
Online Boutique demo app running on the local `kind` cluster, so the
triage agent has real incidents to investigate. Each scenario carries a
ground-truth label (root cause, affected service, expected fix) used later
by the offline eval harness (`eval/`) to score the agent's diagnoses.

Success criteria (from the task):
- Each of the 5 scenarios fires at least one Prometheus alert within ~5
  minutes of injection.
- `chaos revert` always returns the cluster to its exact prior state.
- Each scenario's ground truth is written down in its YAML.

## Scope

In scope: the `chaos` CLI, 5 scenario implementations, YAML scenario
definitions, local state tracking, unit tests with a mocked k8s client.

Out of scope: Argo CD-based deploys (noted in the task as a Step 8
concern — `bad_deploy` uses plain `kubectl`-equivalent API calls for now),
wiring chaos into the agent/eval pipeline, CI integration beyond unit
tests.

## Packaging

`chaos/` becomes a workspace member, consistent with `services/*`:

```
chaos/pyproject.toml          # name = "triage-chaos"
chaos/src/chaos/...
```

Root `pyproject.toml`'s `[tool.uv.workspace] members` changes from
`["services/*"]` to `["services/*", "chaos"]`. `chaos/pyproject.toml`
declares a console script entry point `chaos = "chaos.cli:app"` and
depends on `typer`, `kubernetes`, `pyyaml`.

## Layout

```
chaos/
  pyproject.toml
  src/chaos/
    __init__.py
    cli.py                # Typer app: list, inject, revert, status
    state.py              # active-injection state file read/write
    k8s.py                # thin wrapper over kubernetes.client
    scenarios/
      __init__.py
      base.py              # Scenario ABC
      crash_loop.py
      oom.py
      bad_deploy.py
      slow_redis.py
      cpu_throttle.py
    scenarios/definitions/
      crash_loop.yaml
      oom.yaml
      bad_deploy.yaml
      slow_redis.yaml
      cpu_throttle.yaml
  tests/
    __init__.py
    test_cli.py
    test_state.py
    test_scenarios.py
```

## Components

### `k8s.py` — `K8sClient`

Thin wrapper over `kubernetes.client.AppsV1Api` / `CoreV1Api`, loaded via
`kubernetes.config.load_kube_config()`. Exposes only the methods
scenarios need:

- `get_deployment(namespace, name) -> V1Deployment`
- `patch_deployment(namespace, name, body) -> V1Deployment`
- `exec_in_pod(namespace, pod, container, command) -> str` (used by
  `slow_redis` to call toxiproxy's CLI/API inside the sidecar)
- `list_pods(namespace, label_selector) -> list[V1Pod]` (used to find the
  current redis-cart pod for exec)

Scenario classes depend on this wrapper, never on `kubernetes.client`
directly, so tests can pass a fake/mock implementing the same interface.

### `state.py`

- State file path: `chaos/.state/active.json` (directory gitignored).
- Schema: `{"scenario": str, "service": str, "namespace": str, "injected_at": iso8601, "saved_state": <dict>}`.
- `load() -> ActiveInjection | None`, `save(injection)`, `clear()`.
- `inject` refuses (exits non-zero with a clear message) if a state file
  already exists — only one active scenario at a time.
- `revert` errors if no state file exists.

### `scenarios/base.py` — `Scenario` ABC

```python
class Scenario(ABC):
    name: ClassVar[str]

    @abstractmethod
    def inject(self, k8s: K8sClient, service: str) -> dict[str, Any]:
        """Apply the fault. Returns a JSON-serializable snapshot of
        whatever was overwritten, to be persisted in state.saved_state
        and handed back to revert()."""

    @abstractmethod
    def revert(self, k8s: K8sClient, service: str, saved_state: dict[str, Any]) -> None:
        """Restore exactly what inject() overwrote, using saved_state."""

    @abstractmethod
    def ground_truth(self, service: str) -> dict[str, Any]:
        """root_cause_label, affected_service, expected_fix — loaded from
        this scenario's YAML, with affected_service filled from the
        --service argument (or the scenario's fixed target)."""
```

Each scenario YAML (`scenarios/definitions/<name>.yaml`) holds static
fields:

```yaml
name: crash_loop
description: "Bad env var on paymentservice causes CrashLoopBackOff"
root_cause_label: "bad configuration (invalid environment variable)"
expected_fix: "Revert PORT env var to its original numeric value"
fixed_service: paymentservice   # null for scenarios needing --service
default_params:
  memory_limit: "20Mi"           # oom only
  cpu_limit: "10m"               # cpu_throttle only
  latency_ms: 2000                # slow_redis only
```

`affected_service` is not stored in YAML — it's computed at runtime
(`fixed_service` if set, else the `--service` value) and merged into the
ground-truth dict returned by `ground_truth()`.

### `cli.py` — Typer app

- `chaos list` — loads every YAML in `scenarios/definitions/`, prints
  name + description + whether it takes `--service`.
- `chaos inject <scenario> [--service NAME]`:
  1. Error if `state.load()` is not `None` ("scenario X already active on
     service Y, run `chaos revert` first").
  2. Resolve the scenario class by name; error with the `list` output if
     unknown.
  3. If the scenario needs `--service` and it's missing, error listing
     the 12 valid Online Boutique deployment names. `crash_loop` ignores
     `--service` (fixed: paymentservice). `slow_redis` ignores `--service`
     (fixed: redis-cart).
  4. Call `scenario.inject(k8s, service)`, persist the returned snapshot
     via `state.save(...)`.
  5. Print the scenario's `ground_truth(service)` dict so the operator
     sees what was just injected.
- `chaos revert [scenario]` — `scenario` arg is optional/informational
  (must match the active one if given); loads state, dispatches to the
  matching `Scenario.revert()`, then `state.clear()`.
- `chaos status` — prints the active injection (scenario, service,
  injected_at) or "no active injection."

Valid service names list: the 12 Online Boutique deployments
(adservice, cartservice, checkoutservice, currencyservice, emailservice,
frontend, loadgenerator, paymentservice, productcatalogservice,
recommendationservice, redis-cart, shippingservice) — hardcoded as a
constant in `cli.py`, namespace `boutique` hardcoded as the default
(matches `deploy/boutique/overlay`).

## Scenario implementations

All patches use `AppsV1Api.patch_namespaced_deployment` with a strategic
merge patch; all read the current Deployment first to build the
prior-state snapshot before patching.

### 1. `crash_loop` — fixed target: `paymentservice`

- `inject`: read the `paymentservice` container's `env` list. Append/
  overwrite a `PORT` env var with a non-numeric value (`"not-a-port"`),
  which the Go server fails to parse at startup → crash → restart loop.
  Snapshot: prior `env` list.
- `revert`: patch `env` back to the saved list.
- Ground truth: `root_cause_label: "bad configuration (invalid PORT env var)"`,
  `expected_fix: "restore PORT to its original numeric value"`.

### 2. `oom` — requires `--service`

- `inject`: read chosen Deployment's container `resources`. Patch
  `resources.limits.memory` (and `requests.memory` if it exceeds the new
  limit) down to a value below the service's normal working set (default
  `20Mi` from YAML, overridable later if needed). Pod gets OOMKilled on
  next load.
  Snapshot: prior `resources` dict.
- `revert`: patch `resources` back to the saved dict.
- Ground truth: `root_cause_label: "memory limit set below working set (OOMKilled)"`.

### 3. `bad_deploy` — requires `--service`

- `inject`: read chosen Deployment's container `image`. Patch `image` to
  `<same repo>:does-not-exist` → `ErrImagePull`/`ImagePullBackOff`.
  Snapshot: prior `image` string.
- `revert`: patch `image` back to the saved string.
- Ground truth: `root_cause_label: "broken image tag in deployment"`,
  `expected_fix: "roll back to the previous known-good image tag"`.
- Note: plain Kubernetes API patch for now; Argo CD comes in Step 8 per
  CLAUDE.md.

### 4. `slow_redis` — fixed target: `redis-cart`

- `inject`:
  1. Read the full `redis-cart` Deployment pod spec (`containers` list).
  2. Patch: override the `redis` container's `command` to
     `["redis-server", "--port", "6380"]` (shifts its internal listen
     port off 6379); add a second container `toxiproxy` (image
     `ghcr.io/shopify/toxiproxy:2.9.0`) with no ports needed beyond
     6379, started with `toxiproxy-server`.
  3. Wait for the new pod to be ready, then `exec_in_pod` to run
     `toxiproxy-cli create redis -l 0.0.0.0:6379 -u 127.0.0.1:6380` and
     `toxiproxy-cli toxic add redis -t latency -a latency=<latency_ms>`
     inside the `toxiproxy` container.
  4. Snapshot: the full prior `containers` list (so revert restores the
     original single-container pod spec exactly, dropping toxiproxy
     entirely).
- `revert`: patch `containers` back to the saved single-container list.
- Ground truth: `root_cause_label: "network latency injected in front of redis-cart"`,
  `expected_fix: "remove the toxiproxy sidecar / latency toxic"`.
- The Service object is untouched in both directions — it already
  targets port 6379 on the pod, which now resolves to toxiproxy.

### 5. `cpu_throttle` — requires `--service`

- `inject`: same shape as `oom` but patches `resources.limits.cpu` (and
  `requests.cpu` if needed) down to a value far below normal (default
  `10m` from YAML) on a service expected to be under load (e.g.
  recommendationservice, frontend).
  Snapshot: prior `resources` dict.
- `revert`: patch `resources` back to the saved dict.
- Ground truth: `root_cause_label: "CPU limit set far below demand (throttling)"`.

## Testing

- `tests/test_state.py`: load/save/clear round-trip against a temp file
  path; `inject` refuses when a state file exists; `revert` errors when
  none exists.
- `tests/test_scenarios.py`: for each of the 5 scenarios, a fake
  `K8sClient` (hand-written stub, not a cluster) records calls and
  returns canned `V1Deployment`-shaped dicts/objects. Assert:
  - `inject()` builds the expected patch body and returns the expected
    snapshot.
  - `revert()` issues a patch that restores exactly the snapshot.
  - `ground_truth()` returns the right `root_cause_label` /
    `affected_service` / `expected_fix` for a given `--service`.
- `tests/test_cli.py`: Typer `CliRunner`, with `K8sClient` and the state
  file path monkeypatched to a temp dir. Covers: `list` output includes
  all 5 scenarios; `inject` happy path writes state and calls the right
  scenario; `inject` while active errors without calling inject again;
  `revert` restores and clears state; `revert` with nothing active
  errors; `status` reflects empty and active states.
- No test touches a real cluster — `kubernetes.config.load_kube_config()`
  is only called from the real `K8sClient`, never from test code.

## Open items deferred (not blocking this spec)

- Exact OOM/CPU-throttle threshold values may need tuning once run
  against the real cluster to reliably trip within ~5 minutes — YAML
  `default_params` are starting points, adjustable without code changes.
- `chaos demo`/Makefile wiring (the `make demo` target currently says
  "TODO") is a follow-up, not part of this spec.
