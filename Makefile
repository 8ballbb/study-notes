.DEFAULT_GOAL := help
.PHONY: help setup doctor db test test-browser

help: ## Show the available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-13s\033[0m %s\n", $$1, $$2}'

setup: ## One-command setup: install deps, start services, Chromium (plan → confirm → run)
	./scripts/setup.sh

doctor: ## Check the environment (read-only; reports what's missing)
	./scripts/doctor.sh

db: ## Start the Postgres + pgvector database
	docker compose up -d

test: ## Run the fast, token-free test suite (no e2e, no browser, no Docker)
	uv run pytest -m "not slow and not docker and not e2e and not browser"

test-browser: ## Run the Playwright browser tests (needs `playwright install chromium`)
	uv run pytest -m browser
