# chaos

A Typer CLI (`chaos`) that injects and reverts fault scenarios against
Online Boutique on the local `kind` cluster, to trigger Prometheus alerts
for the triage agent to investigate. Each scenario carries a ground-truth
label (root cause, affected service, expected fix) used by the offline
eval harness (`eval/`) to score the agent's diagnoses.

See [`docs/superpowers/specs/2026-10-13-chaos-cli-design.md`](../docs/superpowers/specs/2026-10-13-chaos-cli-design.md)
for the full design.

## Usage

```bash
chaos list                        # show all scenarios and their descriptions
chaos inject crash_loop           # fixed target (paymentservice); --service not needed
chaos inject oom --service cartservice
chaos status                      # show the active injection, if any
chaos revert                      # restore the cluster to its prior state
```

Only one scenario may be active at a time; `inject` refuses if another is
already active, and `revert` restores exactly what `inject` overwrote.

Note: `bad_deploy` requires Gitea and Argo CD to be running (provisioned
by `make up`) — it injects/reverts its fault via a Git commit that Argo
CD syncs, not a direct Kubernetes API call like the other scenarios.
It needs `GITEA_REPO_URL`, `ARGOCD_URL`, and `ARGOCD_TOKEN` set (see
`.env.example`, which documents how to mint an `ARGOCD_TOKEN` via
`argocd login` + `argocd account generate-token`).

## Scenarios

| Scenario | Target | Root cause |
| --- | --- | --- |
| `crash_loop` | `paymentservice` (fixed) | bad `PORT` env var → CrashLoopBackOff |
| `oom` | `--service` (required) | memory limit set below working set → OOMKilled |
| `bad_deploy` | `--service` (required) | broken image tag → ImagePullBackOff |
| `cpu_throttle` | `--service` (required) | CPU limit set far below demand → throttling |
| `slow_redis` | `redis-cart` (fixed) | toxiproxy sidecar adds latency in front of redis |

## Development

```bash
uv run --all-packages pytest chaos/tests/ -v   # chaos's own test suite
uv run --all-packages ruff check chaos/
uv run --all-packages mypy chaos/
```

Note the `--all-packages` flag: this repo's root `pyproject.toml` has no
dependencies of its own, so a bare `uv run`/`uv sync` only resolves the
root's (empty) closure and silently drops every workspace member,
including `chaos` itself.
