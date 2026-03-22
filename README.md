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

# Open the monitoring dashboard (root URL redirects automatically)
open http://localhost:8000/

# Verify services are running
curl http://localhost:8000/health
# → {"status": "ok", "timestamp": "..."}

# Qdrant dashboard
open http://localhost:6333/dashboard

# Stop services
make down
```

## Docker Hot Reload (Optional)

For faster iteration when working on backend code inside Docker, copy the provided
override template and restart:

```bash
cp docker-compose.override.yml.example docker-compose.override.yml
make restart
```

`docker-compose.override.yml` is gitignored (personal dev config). It mounts
`backend/` and `frontend/` as live volumes and adds uvicorn `--reload` so code
changes take effect without rebuilding the image.

## Dashboard

A built-in monitoring dashboard is available at:

```
http://localhost:8000/
```

The root URL (`/`) automatically redirects to `/dashboard/`. You can also navigate there directly.

It shows real-time service health, index statistics, recent file watcher events,
a search playground for testing queries, and a vault browser with note link
exploration. The dashboard auto-refreshes every 5 seconds.

Dashboard search UX includes:

- Instant keyword search with 300ms debounce
- `Cmd/Ctrl+K` shortcut to focus search
- Result count + search latency feedback
- Fuzzy typo correction fallback with inline **Did you mean** suggestions when initial retrieval has no hits
- Highlighted snippets, tag pills, and related-note suggestions
- One-click **Open in Obsidian** links from search results, vault notes, and link relations

If deep links are unavailable, the dashboard shows an inline warning with setup guidance.
In the Vault Browser, use `Show links` to inspect backlinks/outlinks and the
`Open` chip to launch Obsidian.
When running in Docker, vault name detection uses your host `OBSIDIAN_VAULT_PATH`
automatically, and `OBSIDIAN_VAULT_NAME` remains available as an explicit override.

## Port Configuration

All host-facing ports are configurable via environment variables to avoid conflicts
with other services on the same machine. Defaults match the standard ports:

| Variable | Default | Description |
|----------|---------|-------------|
| `OBSIDIAN_VAULT_NAME` | _(auto-derived from `OBSIDIAN_VAULT_PATH`)_ | Optional override for Obsidian deep-link vault name |
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

## Logging Configuration

The backend uses structured logging with `structlog` and includes request
correlation IDs for API tracing.

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`) |
| `LOG_FORMAT` | `json` | Log output format (`json` for Docker/aggregation, `console` for local readability) |
| `LOG_INCLUDE_QUERY_TEXT` | `false` | Include raw query text in logs. Keep disabled by default for privacy. |
| `DEBUG_ENDPOINTS` | `false` | Enables developer-only debug APIs such as `POST /debug/tokenize`. |
| `LOG_FILE_ENABLED` | `true` | Write logs to a file in addition to stdout. |
| `LOG_DIR` | `/app/logs` | Directory for log files inside the container (bind-mounted to `./logs/` on host). |

When `LOG_FORMAT=json`, each log line is machine-parseable and includes fields
like `timestamp`, `level`, `logger`, and request-scoped `request_id`.

```bash
# Example: verbose local debugging with readable console output
LOG_LEVEL=DEBUG
LOG_FORMAT=console
```

### Log Files

When `LOG_FILE_ENABLED=true` (the default in Docker), logs are written to `./logs/sbi.log`
on the host machine (bind-mounted from `/app/logs` inside the container):

```
logs/
  sbi.log              # current day — always the active file
  sbi.log.2026-03-22   # previous day (rotated at UTC midnight)
  sbi.log.2026-03-21   # 2 days ago
  sbi.log.2026-03-20   # 3 days ago (oldest retained; older files deleted automatically)
```

The file handler always writes newline-delimited JSON, independent of `LOG_FORMAT`.
This makes log files ideal for post-mortem analysis with `jq`:

```bash
# Tail the live log file
make logs-file

# Filter errors across the current log file
make logs-search QUERY='select(.level=="error")'

# Find all events for a specific request ID
cat logs/sbi.log | jq 'select(.request_id=="abc-123")'

# Count events by level
cat logs/sbi.log | jq -s 'group_by(.level) | map({level: .[0].level, count: length})'
```

> **Local dev (outside Docker):** File logging is disabled by default (`LOG_FILE_ENABLED=false`).
> Add `LOG_FILE_ENABLED=true` (and optionally `LOG_DIR=./logs`) to `.env` to enable it locally.

## Local Development

```bash
# One-step setup: creates .venv, installs all dev dependencies via uv,
# and installs pre-commit hooks (runs ruff + mypy on every commit)
make setup

# Activate the virtual environment
source .venv/bin/activate

# Run the FastAPI server locally with hot reload
# Requires Qdrant running (e.g. via `make up`) or QDRANT_URL env var
make dev

# Run tests with coverage
make test

# Lint, format, type-check individually
make lint          # ruff check (no auto-fix)
make format        # ruff format + ruff check --fix
make typecheck     # mypy backend/

# Full CI gate locally (mirrors all CI checks)
make check
```

**Why uv?** `uv` is a Rust-based package manager from the Astral team (same authors as ruff). It replaces `pip` for 10-100x faster installs and is used in both `make setup` and CI.

**Pre-commit hooks** run automatically on `git commit` and enforce ruff lint, ruff format, and mypy. To run them manually on all files:

```bash
.venv/bin/pre-commit run --all-files
```

## Makefile Targets

Run `make help` to see this list at any time.

### Docker

| Target | Description |
|--------|-------------|
| `make up` | Start all services (backend + Qdrant), rebuilding images |
| `make down` | Stop all services |
| `make restart` | Stop, rebuild, and restart all services |
| `make build` | Build Docker images without starting |
| `make logs` | Tail logs from all running services |
| `make status` | Show running container status |
| `make shell` | Open a bash shell in the backend container |
| `make clean` | Stop services, remove volumes, purge caches |

### Development

| Target | Description |
|--------|-------------|
| `make setup` | Create `.venv`, install dev deps via `uv`, install pre-commit hooks |
| `make dev` | Run FastAPI locally with hot reload (`--reload`) |
| `make test` | Run test suite with coverage |
| `make lint` | Ruff lint check (no auto-fix) |
| `make format` | Auto-format and apply safe lint fixes |
| `make format-check` | Check formatting without modifying files (matches CI) |
| `make typecheck` | Run mypy static type checks |
| `make audit` | Run `pip-audit` security scan on runtime deps |
| `make check` | Full CI gate: lint + format-check + typecheck + tests |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Service health check |
| `GET` | `/config/vault` | Resolve vault name used by Obsidian deep links |
| `POST` | `/augment` | **Recommended** — classify intent, retrieve context, return augmented prompt |
| `POST` | `/search` | Semantic + keyword hybrid search (raw results) |
| `POST` | `/note/suggest-links` | Suggest wikilinks and tags for draft note content |
| `POST` | `/intent/classify` | Standalone intent classification |
| `POST` | `/index/rebuild` | Trigger full vault re-index |
| `GET` | `/index/status` | Index health and statistics |
| `GET` | `/index/events` | Recent file watcher events |
| `GET` | `/index/notes` | List all indexed notes |
| `GET` | `/note/{path}/links` | Backlinks and outlinks for a note |
| `POST` | `/debug/tokenize` | Developer-only tokenizer diagnostics (requires `DEBUG_ENDPOINTS=true`) |

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
  "did_you_mean": null,
  "results": [
    {
      "chunk_id": "notes/adr-005.md::0",
      "note_path": "notes/adr-005.md",
      "note_title": "ADR-005: Database Migration Strategy",
      "content": "We decided to use Flyway for database migrations because...",
      "score": 0.87,
      "heading_context": "Decision",
      "highlights": ["... use Flyway for database migrations because ..."],
      "tags": ["#architecture", "#decision"]
    }
  ],
  "related_notes": [
    {
      "note_path": "concepts/flyway.md",
      "note_title": "flyway",
      "relationship": "outgoing",
      "link_count": 2
    }
  ],
  "total_hits": 1,
  "search_time_ms": 45.2,
  "applied_filters": null
}
```

### Search with metadata filters (tags, path, date)

`POST /search` accepts optional `filters` to constrain retrieval before ranking:

- `tags`: include notes with any of these tags
- `exclude_tags`: exclude notes with any of these tags
- `path_prefix`: include notes whose `note_path` matches this folder/prefix
- `modified_after` / `modified_before`: include notes inside a last-modified datetime window

**Important:** `path_prefix` filtering requires all chunks to carry path-prefix payloads.
If the index was built before this feature, using `path_prefix` returns **HTTP 409**
with `error_code: "INDEX_REBUILD_REQUIRED"`. Run a full rebuild to fix this:

```bash
curl -X POST http://localhost:8000/index/rebuild
```

```bash
curl -X POST http://localhost:8000/search \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "deployment pipeline",
    "top_k": 10,
    "filters": {
      "tags": ["devops", "ci-cd"],
      "exclude_tags": ["archive"],
      "path_prefix": "projects/infrastructure/",
      "modified_after": "2025-01-01T00:00:00Z",
      "modified_before": "2026-01-01T00:00:00Z"
    }
  }'
```

Filtered response includes an `applied_filters` echo for traceability:

```json
{
  "query": "deployment pipeline",
  "results": [],
  "related_notes": [],
  "total_hits": 0,
  "search_time_ms": 24.5,
  "did_you_mean": null,
  "applied_filters": {
    "tags": ["devops", "ci-cd"],
    "exclude_tags": ["archive"],
    "path_prefix": "projects/infrastructure/",
    "modified_after": "2025-01-01T00:00:00Z",
    "modified_before": "2026-01-01T00:00:00Z"
  }
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
For search filter details, see [docs/agents/SEARCH_FILTERS.md](docs/agents/SEARCH_FILTERS.md).
For service management and debugging, see [docs/agents/DEVELOPER_GUIDE.md](docs/agents/DEVELOPER_GUIDE.md).

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

## Multilingual Support (CJK)

The service supports Chinese, Japanese, and English content in Obsidian vaults:

- **Dense embeddings** use `paraphrase-multilingual-MiniLM-L12-v2` (50+ languages, 384 dims)
- **Sparse/BM25 indexing** pre-tokenizes CJK text with language-aware NLP:
  - **Japanese**: SudachiPy morphological analysis with POS-based stopword filtering (removes particles, auxiliary verbs, symbols — keeps nouns, verbs, adjectives)
  - **Chinese**: jieba word segmentation with POS-based stopword filtering (removes function words like 的, 了, 关于)
  - **English**: passed through unchanged (fastembed's BM25 handles whitespace-delimited text natively)
- **Markdown tags**: `#日記`, `#数据库`, `#データベース` are recognized alongside ASCII tags
- **Intent classification**: CJK keywords use substring matching (ASCII keywords retain word-boundary precision)
- **Full-width normalization**: NFKC normalization converts full-width characters (e.g. `１` → `1`) before indexing

CJK tokenizer dependencies (`jieba`, `sudachipy`, `sudachidict_core`) are installed automatically.
After upgrading, trigger a full re-index to regenerate embeddings:

```bash
curl -X POST http://localhost:8000/index/rebuild
```

## Architecture

```
backend/
├── domain/          # Pure business logic, Pydantic models
├── application/     # Use-case orchestration (services)
├── infrastructure/  # External system adapters (Qdrant, file watcher, CJK tokenizer)
└── api/             # FastAPI route handlers
frontend/            # Monitoring dashboard (static HTML/CSS/JS)
```

**Read flow:** Agent → `POST /augment` → intent classify → hybrid search (dense + sparse RRF) → graph enrichment → augmented prompt

**Write flow:** Agent → `POST /note/suggest-links` → hybrid search → suggested links/tags → agent writes `.md` to vault → file watcher detects → auto-indexed within 5 seconds

See [docs/design.md](docs/design.md) for the full technical design.
