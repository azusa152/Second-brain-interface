.PHONY: help up down restart test lint format build logs

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

up: ## Start all services (backend + Qdrant)
	docker compose up --build -d

down: ## Stop all services
	docker compose down

restart: ## Restart all services (rebuild images)
	docker compose down && docker compose up --build -d

build: ## Build Docker images without starting
	docker compose build

logs: ## Tail logs from all services
	docker compose logs -f

test: ## Run test suite with coverage
	python -m pytest tests/ -v --cov=backend --cov-report=term-missing

lint: ## Run linter checks
	ruff check backend/ tests/

format: ## Auto-format and fix code
	ruff format backend/ tests/
	ruff check --fix backend/ tests/
