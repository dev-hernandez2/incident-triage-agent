# triage-agent Helm chart

Deploys all five triage-agent services (webhook, agent, bot, executor,
dashboard) plus their RBAC and NetworkPolicies.

## Prerequisites

- Kafka and Postgres already running and reachable (see the root
  `Makefile`'s `up` target, or point `values.yaml`'s `kafka.bootstrapServers`
  at your own).
- Built and pushed images for all five services (see `deploy/*/Dockerfile`
  at the repo root) — this chart does not build images itself. These
  Dockerfiles exist but have not yet been exercised by a real build/CI
  pipeline in this project, so whoever runs them first is the first to
  actually build and run these images end-to-end.
- A Secret with the required env vars (`ANTHROPIC_API_KEY`,
  `DISCORD_BOT_TOKEN`, `DATABASE_URL`, etc. — see `.env.example`), either
  passed via `secrets:` in `values.yaml` (demo/dev only) or referenced via
  `existingSecretName`.

## Install

```bash
helm upgrade --install triage-agent deploy/helm/triage-agent \
  --namespace triage --create-namespace \
  --set image.repository=ghcr.io/<you>/triage \
  --set executor.targetNamespace=boutique \
  -f my-secrets-values.yaml
```

## Note on `executor.targetNamespace`

The executor's `Role`/`RoleBinding` are templated against this namespace
even if it does not exist yet at install time — Kubernetes allows RBAC
objects to reference a namespace that is created later; the executor
only needs the namespace to exist by the time it actually tries to patch
a Deployment in it.

## Note on `agent.allowedNamespaces`

The agent's ServiceAccount has a cluster-wide `ClusterRole`
(`get`/`list`/`watch` only) so it can investigate any namespace a root
cause might live in, not just `executor.targetNamespace`. This value sets
`TRIAGE_ALLOWED_NAMESPACES`, a second, app-level allow-list enforced in
`K8sReadOnlyClient` — it defaults to `"*"` (every namespace); set it to a
comma-separated list (e.g. `boutique,monitoring`) to narrow the agent's
reach below what the `ClusterRole` permits, without changing RBAC or
redeploying the chart's templates.
