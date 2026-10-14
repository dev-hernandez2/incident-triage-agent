# triage-agent

AI agent that investigates Kubernetes alerts with read-only tools and posts a
root-cause summary to Discord for human approval before any remediation runs.

See [`CLAUDE.md`](./CLAUDE.md) for architecture decisions and conventions,
and [`docs/adr/`](./docs/adr/) for design rationale.

## Quickstart (stubs — not yet implemented)

```bash
make up     # kind cluster + Online Boutique + services
make demo   # trigger a chaos scenario end-to-end
make test
make lint
```
