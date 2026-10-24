# triage-agent Helm chart

Deploys all five triage-agent services (webhook, agent, bot, executor,
dashboard) plus their RBAC and NetworkPolicies.

## Prerequisites

- Kafka and Postgres already running and reachable (see the root
  `Makefile`'s `up` target, or point `values.yaml`'s `kafka.bootstrapServers`
  at your own).
- Built and pushed images for all five services (see `deploy/*/Dockerfile`
  at the repo root) — this chart does not build images itself.
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
