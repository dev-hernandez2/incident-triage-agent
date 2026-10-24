# deploy/k8s

Raw Kubernetes manifests for the Online Boutique demo deployment's supporting
infra (kind cluster config, GitOps/ArgoCD bootstrap) on a local kind cluster.

The triage-agent app services (webhook, agent, bot, executor, dashboard) —
including their RBAC and NetworkPolicies — are deployed via the Helm chart
at `deploy/helm/triage-agent/`, not raw manifests here. See
`deploy/helm/triage-agent/README.md` for install instructions and
prerequisites.

## Grafana dashboard ConfigMap

The triage-agent Grafana dashboard JSON lives at
`deploy/monitoring/grafana-agent-dashboard.json` (kept as a separate
committed file so it's reviewable/diffable on its own, rather than
hand-copying it into a manifest). Provision it as a ConfigMap manually:

```bash
kubectl create configmap triage-agent-grafana-dashboard \
  --from-file=deploy/monitoring/grafana-agent-dashboard.json \
  -n monitoring \
  --dry-run=client -o yaml | kubectl apply -f -
```
