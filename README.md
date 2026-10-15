# triage-agent

AI agent that investigates Kubernetes alerts with read-only tools and posts a
root-cause summary to Discord for human approval before any remediation runs.

See [`CLAUDE.md`](./CLAUDE.md) for architecture decisions and conventions,
and [`docs/adr/`](./docs/adr/) for design rationale.

## Quickstart

```bash
make up     # kind cluster + Online Boutique + monitoring stack
make test
make lint
```

`make demo` (trigger a chaos scenario end-to-end and show the Discord
flow) is still a stub pending the agent/bot services. The `chaos` CLI
itself is implemented — see [`chaos/README.md`](./chaos/README.md):

```bash
uv run --all-packages chaos list
uv run --all-packages chaos inject crash_loop
uv run --all-packages chaos status
uv run --all-packages chaos revert
```
