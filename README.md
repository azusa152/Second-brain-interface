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

## Port Configuration

All host-facing ports are configurable via environment variables to avoid conflicts
with other services on the same machine. Defaults match the standard ports:

| Variable | Default | Description |
|----------|---------|-------------|
| `SBI_API_PORT` | `8000` | Backend API port |
| `SBI_QDRANT_HTTP_PORT` | `6333` | Qdrant HTTP / dashboard port |
| `SBI_QDRANT_GRPC_PORT` | `6334` | Qdrant gRPC port |

To customize, copy `.env.example` to `.env` and set the desired values:

```bash
cp .env.example .env
```

```bash
# Example: shift all ports to avoid conflicts
SBI_API_PORT=8080
SBI_QDRANT_HTTP_PORT=16333
SBI_QDRANT_GRPC_PORT=16334
```

Then restart the services:

```bash
make down && make up
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

### Search your vault

```bash
curl -X POST http://localhost:8000/search \
  -H 'Content-Type: application/json' \
  -d '{"query": "database migration decision", "top_k": 5}'
```

Response:
```json
{
  "query": "database migration decision",
  "results": [
    {
      "chunk_id": "notes/adr-005.md::0",
      "note_path": "notes/adr-005.md",
      "note_title": "ADR-005: Database Migration Strategy",
      "content": "We decided to use Flyway for database migrations because...",
      "score": 0.87,
      "heading_context": "Decision",
      "highlights": []
    }
  ],
  "related_notes": [],
  "total_hits": 1,
  "search_time_ms": 45.2
}
```

### Trigger full re-index

```bash
curl -X POST http://localhost:8000/index/rebuild
```

Response:
```json
{
  "status": "success",
  "notes_indexed": 142,
  "chunks_created": 1087,
  "time_taken_seconds": 12.3
}
```

### Check index status

```bash
curl http://localhost:8000/index/status
```

### Get note links

```bash
curl http://localhost:8000/note/notes/adr-005.md/links
```

For full agent integration documentation, see [docs/agents/SKILL.md](docs/agents/SKILL.md).

## Upgrading

If upgrading from a version before hybrid search (Phases 2-5), the existing Qdrant
collection lacks sparse vector configuration. On startup, the service will detect
this and automatically recreate the collection. **You must then trigger a full
re-index** to populate both dense and sparse vectors:

```bash
curl -X POST http://localhost:8000/index/rebuild
```

Alternatively, delete the Qdrant data volume and restart:

```bash
docker compose down -v
docker compose up -d
curl -X POST http://localhost:8000/index/rebuild
```

## Architecture

```
backend/
├── domain/          # Pure business logic, Pydantic models
├── application/     # Use-case orchestration (services)
├── infrastructure/  # External system adapters (Qdrant, file watcher)
└── api/             # FastAPI route handlers
```

See [docs/design.md](docs/design.md) for the full technical design.
