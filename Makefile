.PHONY: up down demo eval test lint

up: ## Create kind cluster, deploy Online Boutique + triage-agent services
	@echo "TODO: kind create cluster; deploy Online Boutique; deploy services/*"

down: ## Tear down the kind cluster
	@echo "TODO: kind delete cluster"

demo: ## Trigger a chaos scenario end-to-end and show the Discord flow
	@echo "TODO: run chaos/ scenario against Online Boutique"

eval: ## Run the offline agent accuracy eval harness
	@echo "TODO: run eval/ harness against recorded incidents"

test: ## Run unit tests
	uv run pytest

lint: ## Run ruff + mypy
	uv run ruff check .
	uv run mypy .
