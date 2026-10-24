# deploy/k8s

Raw Kubernetes manifests for Online Boutique + triage-agent services, for use
with a local kind cluster.

## Grafana dashboard ConfigMap

The `grafana-dashboard-agent.yaml` manifest includes a ConfigMap with a placeholder
for the dashboard JSON. To populate it, apply the manifest with the actual dashboard
file via kubectl:

```bash
kubectl create configmap triage-agent-grafana-dashboard \
  --from-file=deploy/monitoring/grafana-agent-dashboard.json \
  -n monitoring \
  --dry-run=client -o yaml | kubectl apply -f -
```

This keeps the dashboard JSON as a separate committed file (reviewable/diffable on its own)
rather than hand-copying it into the YAML.
