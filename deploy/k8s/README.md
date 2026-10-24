# deploy/k8s

Raw Kubernetes manifests for the Online Boutique demo deployment's supporting
infra (kind cluster config, GitOps/ArgoCD bootstrap) on a local kind cluster.

The triage-agent app services (webhook, agent, bot, executor, dashboard) —
including their RBAC and NetworkPolicies — are deployed via the Helm chart
at `deploy/helm/triage-agent/`, not raw manifests here. See
`deploy/helm/triage-agent/README.md` for install instructions and
prerequisites.
