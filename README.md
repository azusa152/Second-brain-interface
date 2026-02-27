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

## Dashboard

A built-in monitoring dashboard is available at:

```
http://localhost:8000/dashboard
```

It shows real-time service health, index statistics, recent file watcher events,
a search playground for testing queries, and a vault browser with note link
exploration. The dashboard auto-refreshes every 5 seconds.

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
make restart
```

## Local Development

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install runtime + development/testing dependencies
pip install -r requirements-dev.txt

# Run tests with coverage
make test

# Lint and format
make lint
make format
```

## Makefile Targets

| Target | Description |
|--------|-------------|
| `make up` | Start all services (backend + Qdrant), rebuilding images |
| `make down` | Stop all services |
| `make restart` | Stop, rebuild, and restart all services |
| `make logs` | Tail logs from all running services |
| `make build` | Build Docker images without starting |
| `make test` | Run test suite |
| `make lint` | Run linter checks |
| `make format` | Auto-format and fix code |

Run `make help` to see this list at any time.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Service health check |
| `POST` | `/augment` | **Recommended** — classify intent, retrieve context, return augmented prompt |
| `POST` | `/search` | Semantic + keyword hybrid search (raw results) |
| `POST` | `/note/suggest-links` | Suggest wikilinks and tags for draft note content |
| `POST` | `/intent/classify` | Standalone intent classification |
| `POST` | `/index/rebuild` | Trigger full vault re-index |
| `GET` | `/index/status` | Index health and statistics |
| `GET` | `/index/events` | Recent file watcher events |
| `GET` | `/index/notes` | List all indexed notes |
| `GET` | `/note/{path}/links` | Backlinks and outlinks for a note |

### Augment a prompt with vault context

```bash
curl -X POST http://localhost:8000/augment \
  -H 'Content-Type: application/json' \
  -d '{"message": "What was my investment strategy last year?"}'
```

Response when personal context is found:
```json
{
  "retrieval_attempted": true,
  "context_injected": true,
  "intent_confidence": 0.72,
  "triggered_signals": ["keyword:investment", "temporal:last_year"],
  "context_block": { "sources": [...], "total_chars": 312 },
  "augmented_prompt": "[System: ...]\n<context>...</context>\n<instruction>...</instruction>\n\n[User]: ...",
  "search_time_ms": 48.3
}
```

Response for a general (non-personal) query:
```json
{
  "retrieval_attempted": false,
  "context_injected": false,
  "intent_confidence": 0.04,
  "triggered_signals": [],
  "context_block": null,
  "augmented_prompt": null,
  "search_time_ms": null
}
```

### Search your vault (raw results)

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
      "highlights": [],
      "tags": ["#architecture", "#decision"]
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

### Get wikilink suggestions for a draft note

```bash
curl -X POST http://localhost:8000/note/suggest-links \
  -H 'Content-Type: application/json' \
  -d '{"content": "Today I decided to use Flyway for database migrations...", "title": "Migration Strategy Decision"}'
```

Response:
```json
{
  "suggested_wikilinks": [
    {
      "display_text": "ADR-005: Database Migration Strategy",
      "target_path": "notes/adr-005.md",
      "score": 0.87
    }
  ],
  "suggested_tags": ["#architecture", "#decision"],
  "related_notes": [
    {"note_path": "concepts/flyway.md", "note_title": "flyway"}
  ]
}
```

### Get note links

```bash
curl http://localhost:8000/note/notes/adr-005.md/links
```

### Error responses

All error responses share a consistent JSON body:

```json
{
  "error_code": "SEARCH_UNAVAILABLE",
  "message": "Human-readable description of the error."
}
```

| Status | `error_code` | Meaning |
|--------|-------------|---------|
| `409` | `REBUILD_IN_PROGRESS` | A rebuild is already running |
| `404` | `NOTE_NOT_FOUND` | The requested note is not in the index |
| `503` | `*_UNAVAILABLE` | A backend service is not ready |
| `500` | `INTERNAL_SERVER_ERROR` | Unexpected server error |

### CORS

The API enables CORS for all origins (`*`), allowing the built-in `/dashboard`
and any local LLM agent running in a browser context to call the API directly.

For full agent integration documentation, see [docs/agents/SKILL.md](docs/agents/SKILL.md).
For the complete API reference (all endpoints, full schemas), see [docs/agents/API_REFERENCE.md](docs/agents/API_REFERENCE.md).

## Note Creation (Agent Workflow)

The service is read-only and never writes to the vault. Agents (such as OpenClaw) write notes directly to the vault directory. The file watcher automatically detects and indexes new `.md` files within 5 seconds.

**Recommended workflow for agents creating notes:**

1. Draft the note content
2. Call `POST /note/suggest-links` with the draft content and title to get wikilink and tag suggestions
3. Write the `.md` file to the vault directory with the suggested links and frontmatter
4. The service indexes the note automatically — no manual step required

Use this frontmatter template for agent-created notes:

```yaml
---
title: "{title}"
date: "{YYYY-MM-DD}"
tags: [{suggested_tags}]
created_by: openclaw
---
```

The `created_by: openclaw` field lets you distinguish agent-created notes from manually written ones.

## OpenClaw Integration

Add the following to your OpenClaw memory or persona instructions to enable proactive note creation in your Obsidian vault.

Replace `{VAULT_PATH}` with your vault path (e.g., `~/obsidian-vault`).

---

**Obsidian Vault Access**

You can read from and write to the user's Obsidian vault at `{VAULT_PATH}`.
A knowledge bridge service at `http://localhost:8000` indexes the vault for
semantic search. Install the `obsidian-knowledge-bridge` skill from
`docs/agents/SKILL.md` to use it.

**Reading (automatic):** Use the `obsidian-knowledge-bridge` skill. The
`POST /augment` endpoint classifies intent and retrieves context automatically.

**Writing notes:** When you encounter information worth preserving, create a
note in the vault. Do not ask for permission each time — use your judgment.

Worth preserving:
- Decisions made and their reasoning
- Key insights or discoveries
- Meeting summaries and action items
- Useful references or comparisons
- Project plans or architecture decisions

Not worth preserving:
- Trivial questions or small talk
- Information already in existing notes
- Temporary or ephemeral context

Steps to create a note:
1. Draft the content in markdown
2. Call `POST http://localhost:8000/note/suggest-links` with
   `{"content": "...", "title": "..."}` to get wikilink and tag suggestions
3. Write the `.md` file to `{VAULT_PATH}/inbox/` (or a more specific folder
   if obvious) using this frontmatter template:

```yaml
---
title: "{title}"
date: "{YYYY-MM-DD}"
tags: [{suggested_tags}]
created_by: openclaw
---
```

4. Incorporate the suggested `[[wikilinks]]` into the note body where relevant
5. The service auto-indexes new notes within 5 seconds

If `POST /note/suggest-links` returns 503, write the note without suggestions —
it will still be indexed and searchable.

---

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
frontend/            # Monitoring dashboard (static HTML/CSS/JS)
```

**Read flow:** Agent → `POST /augment` → intent classify → hybrid search (dense + sparse RRF) → graph enrichment → augmented prompt

**Write flow:** Agent → `POST /note/suggest-links` → hybrid search → suggested links/tags → agent writes `.md` to vault → file watcher detects → auto-indexed within 5 seconds

See [docs/design.md](docs/design.md) for the full technical design.
