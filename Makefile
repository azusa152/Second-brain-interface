# ============================================================================ #
# Second Brain Interface — Developer Makefile
# Usage: make <target>   |   Run `make` or `make help` to list all targets
# ============================================================================ #

COMPOSE  := docker compose
VENV_BIN := .venv/bin
PYTHON   := $(VENV_BIN)/python
RUFF     := $(VENV_BIN)/ruff
PYTEST   := $(VENV_BIN)/pytest
SRC_DIRS := backend/ tests/

# Guard used by dev targets that require the venv to exist
_require_venv:
	@test -f $(PYTHON) || { echo "Error: venv not found. Run 'make setup' first."; exit 1; }

# ---------------------------------------------------------------------------- #
# Default                                                                       #
# ---------------------------------------------------------------------------- #

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help message
	@printf "\nUsage: make \033[36m<target>\033[0m\n"
	@awk 'BEGIN {FS = ":.*##"} \
	      /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } \
	      /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2 }' \
	     $(MAKEFILE_LIST)
	@printf "\n"

# ---------------------------------------------------------------------------- #
# Docker                                                                        #
# ---------------------------------------------------------------------------- #

##@ Docker

.PHONY: up down restart build logs logs-backend logs-qdrant status shell clean

up: ## Start all services (backend + Qdrant)
	$(COMPOSE) up --build -d

down: ## Stop all services
	$(COMPOSE) down

restart: ## Restart all services (rebuild images)
	$(COMPOSE) down && $(COMPOSE) up --build -d

build: ## Build Docker images without starting
	$(COMPOSE) build

status: ## Show running container status
	$(COMPOSE) ps

logs: ## Tail logs from all services
	$(COMPOSE) logs -f

logs-backend: ## Tail logs from the backend service only
	$(COMPOSE) logs -f backend

logs-qdrant: ## Tail logs from the Qdrant service only
	$(COMPOSE) logs -f qdrant

shell: ## Open a bash shell inside the running backend container
	$(COMPOSE) exec backend bash

clean: ## Stop services, remove volumes, and purge Python caches
	$(COMPOSE) down -v
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache  -exec rm -rf {} + 2>/dev/null || true

# ---------------------------------------------------------------------------- #
# Development                                                                   #
# ---------------------------------------------------------------------------- #

##@ Development

.PHONY: setup test lint format check _require_venv

setup: ## Create .venv and install all dependencies
	python3 -m venv .venv
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install ruff pytest pytest-cov pytest-asyncio

test: _require_venv ## Run test suite with coverage
	$(PYTEST) tests/ -v --cov=backend --cov-report=term-missing

lint: _require_venv ## Run linter checks (no auto-fix)
	$(RUFF) check $(SRC_DIRS)

format: _require_venv ## Auto-format and apply safe lint fixes
	$(RUFF) format $(SRC_DIRS)
	$(RUFF) check --fix $(SRC_DIRS)

check: _require_venv ## Run lint then tests — single CI gate
	$(RUFF) check $(SRC_DIRS)
	$(PYTEST) tests/ -v --cov=backend --cov-report=term-missing
