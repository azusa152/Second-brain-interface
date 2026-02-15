# OpenClaw-Obsidian Knowledge Bridge

Local RAG middleware that grants OpenClaw (AI Agent) semantic understanding and retrieval capabilities over your Obsidian vault.

## Prerequisites

- Docker & Docker Compose
- Python 3.12+ (for local development)
- An Obsidian vault directory

## Quick Start

```bash
# Start all services (backend + Qdrant)
make up

# Verify services are running
curl http://localhost:8000/health
# → {"status": "ok", "timestamp": "..."}

# Qdrant dashboard
open http://localhost:6333/dashboard

# Stop services
make down
```

## Local Development

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run tests
make test

# Lint and format
make lint
make format
```

## Makefile Targets

Run `make help` to see all available targets.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Service health check |
| `POST` | `/search` | Semantic + keyword hybrid search |
| `POST` | `/index/rebuild` | Trigger full vault re-index |
| `GET` | `/index/status` | Index health and statistics |
| `GET` | `/note/{path}/links` | Backlinks and outlinks for a note |

## Architecture

```
backend/
├── domain/          # Pure business logic, Pydantic models
├── application/     # Use-case orchestration (services)
├── infrastructure/  # External system adapters (Qdrant, file watcher)
└── api/             # FastAPI route handlers
```

See [docs/design.md](docs/design.md) for the full technical design.
