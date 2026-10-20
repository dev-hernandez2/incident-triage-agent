.PHONY: up down demo eval test lint

export KIND_EXPERIMENTAL_PROVIDER := podman

CLUSTER_NAME := triage
KUBE_PROMETHEUS_STACK_VERSION := 92.3.1
LOKI_CHART_VERSION := 7.3.0
PROMTAIL_CHART_VERSION := 6.17.1

up: ## Create kind cluster, deploy Online Boutique + monitoring stack
	@if kind get clusters 2>/dev/null | grep -qx "$(CLUSTER_NAME)"; then \
		echo "kind cluster '$(CLUSTER_NAME)' already exists, skipping create"; \
	else \
		kind create cluster --name $(CLUSTER_NAME) --config deploy/k8s/kind-config.yaml; \
	fi
	kubectl config use-context kind-$(CLUSTER_NAME)
	kubectl apply -k deploy/boutique/overlay/
	kubectl wait --for=condition=Available deployment --all -n boutique --timeout=300s
	helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
	helm repo add grafana https://grafana.github.io/helm-charts >/dev/null 2>&1 || true
	helm repo update prometheus-community grafana
	kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
	helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
		--version $(KUBE_PROMETHEUS_STACK_VERSION) \
		--namespace monitoring \
		-f deploy/monitoring/kube-prometheus-stack-values.yaml \
		--wait --timeout 5m
	helm upgrade --install loki grafana/loki \
		--version $(LOKI_CHART_VERSION) \
		--namespace monitoring \
		-f deploy/monitoring/loki-values.yaml \
		--wait --timeout 5m
	helm upgrade --install promtail grafana/promtail \
		--version $(PROMTAIL_CHART_VERSION) \
		--namespace monitoring \
		-f deploy/monitoring/promtail-values.yaml \
		--wait --timeout 5m
	kubectl apply -f deploy/monitoring/boutique-alerts.yaml
	helm repo add bitnami https://charts.bitnami.com/bitnami >/dev/null 2>&1 || true
	helm repo update bitnami
	kubectl create namespace triage --dry-run=client -o yaml | kubectl apply -f -
	kubectl apply -f deploy/k8s/rbac-triage-agent.yaml
	helm upgrade --install kafka bitnami/kafka \
		--namespace triage \
		-f deploy/helm/kafka-values.yaml \
		--wait --timeout 5m
	helm upgrade --install postgres bitnami/postgresql \
		--namespace triage \
		-f deploy/helm/postgres-values.yaml \
		--wait --timeout 5m
	kubectl port-forward -n triage svc/postgres-postgresql 5432:5432 >/tmp/triage-pg-forward.log 2>&1 & \
		PG_PID=$$!; \
		for i in $$(seq 1 30); do \
			nc -z localhost 5432 && break; \
			sleep 1; \
		done; \
		DATABASE_URL=postgresql://triage:triage@localhost:5432/triage \
			uv run --package triage-db alembic -c db/alembic.ini upgrade head; \
		RC=$$?; \
		kill $$PG_PID; \
		exit $$RC
	@echo ""
	@echo "Online Boutique and monitoring stack are up."
	@echo "Grafana:    http://localhost:3000  (run: kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80)"
	@echo "Prometheus: http://localhost:9090  (run: kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090)"
	@echo "Boutique:   http://localhost:8080  (run: kubectl port-forward -n boutique svc/frontend-external 8080:80)"
	@echo "Grafana login: admin / admin"
	@echo "Kafka:      kubectl port-forward -n triage svc/kafka 9092:9092"
	@echo "Postgres:   kubectl port-forward -n triage svc/postgres-postgresql 5432:5432"
	@echo "Run webhook/agent locally against those forwarded ports (see .env.example)."

down: ## Tear down the kind cluster
	kind delete cluster --name $(CLUSTER_NAME)

demo: ## Trigger a chaos scenario end-to-end and show the Discord flow
	@echo "TODO: run chaos/ scenario against Online Boutique"

eval: ## Run the offline agent accuracy eval harness
	@echo "TODO: run eval/ harness against recorded incidents"

test: ## Run unit tests
	uv run pytest

lint: ## Run ruff + mypy
	uv run ruff check .
	uv run mypy .
