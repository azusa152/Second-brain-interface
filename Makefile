# ============================================================================ #
# Second Brain Interface — Developer Makefile
# Usage: make <target>   |   Run `make` or `make help` to list all targets
# ============================================================================ #

COMPOSE       := docker compose
VENV_BIN      := .venv/bin
PYTHON        := $(VENV_BIN)/python
UV            := $(VENV_BIN)/uv
RUFF          := $(VENV_BIN)/ruff
PYTEST        := $(VENV_BIN)/pytest
MYPY          := $(VENV_BIN)/mypy
PIP_AUDIT     := $(VENV_BIN)/pip-audit
PRE_COMMIT    := $(VENV_BIN)/pre-commit
SRC_DIRS      := backend/ tests/

# jq expression shared by logs-pretty and logs-pretty-follow
_LOG_JQ_PRETTY := "\(.timestamp) [\(.level | ascii_upcase)] \(.logger): \(.event)" + if .path then " (\(.method) \(.path) \(.status_code) \(.duration_ms)ms)" else "" end

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

.PHONY: up down restart build logs logs-backend logs-qdrant logs-file logs-search logs-pretty logs-pretty-follow logs-errors status shell clean

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

logs-file: ## Tail the current log file on host (waits for file if not yet created)
	tail -F logs/sbi.log

logs-search: ## Search log file with jq (usage: make logs-search QUERY='select(.level=="error")')
	@test -n "$(QUERY)" || { echo 'Usage: make logs-search QUERY='"'"'select(.level=="error")'"'"''; exit 1; }
	@jq '$(QUERY)' logs/sbi.log

logs-pretty: ## Human-readable one-line-per-event view of the log file (requires jq)
	@jq -r '$(_LOG_JQ_PRETTY)' logs/sbi.log

logs-pretty-follow: ## Live-follow log file in human-readable format (requires jq; waits if file absent)
	@tail -F logs/sbi.log | jq -r '$(_LOG_JQ_PRETTY)'

logs-errors: ## Show only warnings and errors from the log file
	@jq 'select(.level == "warning" or .level == "error")' logs/sbi.log

shell: ## Open a bash shell inside the running backend container
	$(COMPOSE) exec backend bash

clean: ## Stop services, remove volumes, and purge Python caches
	$(COMPOSE) down -v
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache  -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache  -exec rm -rf {} + 2>/dev/null || true

# ---------------------------------------------------------------------------- #
# Development                                                                   #
# ---------------------------------------------------------------------------- #

##@ Development

.PHONY: setup dev test lint format format-check typecheck audit check _require_venv

setup: ## Create .venv, install all dev dependencies, and install pre-commit hooks
	python3 -m venv .venv
	$(PYTHON) -m pip install --upgrade pip uv
	$(UV) pip install -r requirements-dev.txt
	$(PRE_COMMIT) install
	@printf "\nSetup complete. Run 'make check' to verify everything works.\n"

dev: _require_venv ## Run FastAPI server locally with hot reload (requires Qdrant on localhost:6333)
	OBSIDIAN_VAULT_PATH=./_vault QDRANT_URL=http://localhost:6333 $(PYTHON) -m uvicorn backend.main:app --reload --port 8000

test: _require_venv ## Run test suite with coverage
	$(PYTEST) tests/ -v --cov=backend --cov-report=term-missing

lint: _require_venv ## Run linter checks (no auto-fix)
	$(RUFF) check $(SRC_DIRS)

format: _require_venv ## Auto-format and apply safe lint fixes
	$(RUFF) format $(SRC_DIRS)
	$(RUFF) check --fix $(SRC_DIRS)

format-check: _require_venv ## Check formatting without modifying files (matches CI)
	$(RUFF) format --check $(SRC_DIRS)

typecheck: _require_venv ## Run static type checks with mypy
	$(MYPY) backend/

audit: _require_venv ## Run security audit on runtime dependencies
	$(PIP_AUDIT) --desc -r requirements.txt --ignore-vuln CVE-2026-25990

check: _require_venv ## Full CI gate: lint + format-check + typecheck + tests (run 'make audit' separately)
	$(RUFF) check $(SRC_DIRS)
	$(RUFF) format --check $(SRC_DIRS)
	$(MYPY) backend/
	$(PYTEST) tests/ -v --cov=backend --cov-report=term-missing
