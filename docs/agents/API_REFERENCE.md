# OpenClaw-Obsidian Knowledge Bridge — Full API Reference

**Base URL**: `http://localhost:8000` (default; configurable via `SBI_API_PORT` in `.env`)

> This is the complete API reference for developers. For the compact agent skill used by OpenClaw, see [SKILL.md](SKILL.md).

## Service Management

Use `make` commands to control the service lifecycle:

| Command | Description |
|---------|-------------|
| `make up` | Start all services (backend + Qdrant), rebuilding images |
| `make down` | Stop all services |
| `make restart` | Stop, rebuild, and restart all services |
| `make logs` | Tail logs from all running services |
| `make build` | Build Docker images without starting |

> Use `make restart` after code changes or when the service is in an unhealthy state.

## Constraints

- **Read-only vault**: The middleware never modifies Obsidian notes. All operations are read-only, except agents writing notes directly to the vault directory.
- **Index must be built first**: Before searching, trigger a full index rebuild via `POST /index/rebuild`. The file watcher keeps the index updated after the initial build.
- **Local only**: All processing (embedding, indexing, search) happens on the user's machine. No external API calls.

## Request Correlation and Logging

- Send `X-Request-ID` on incoming requests to correlate API, application, and infrastructure logs.
- If missing, the backend generates a request ID and returns it in the response header.
- Logging environment variables:
  - `LOG_LEVEL` (default `INFO`)
  - `LOG_FORMAT` (default `json`; supports `json` or `console`)
  - `LOG_INCLUDE_QUERY_TEXT` (default `false`; keep disabled for privacy)

## Endpoints

> **Recommended primary endpoint**: Use `POST /augment` for most agent interactions.
> It classifies intent, retrieves context when needed, and returns a ready-to-inject prompt —
> all in one call. Use `POST /search` only when you need raw search results without prompt formatting.

### 1. Augment Prompt — `POST /augment` ⭐ Recommended

Classify intent, retrieve relevant vault context when needed, and return a fully assembled augmented prompt ready for LLM injection. This is the single-call interface for proactive context retrieval.

**Request**:
```json
{
  "message": "What was my investment strategy last year?",
  "top_k": 3,
  "include_sources": true
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `message` | string | *required* | The user's message to classify and augment |
| `top_k` | int | 3 | Max number of vault chunks to inject (1–20) |
| `include_sources` | bool | true | Include source citations in `context_block` |

**Response — context injected** (200):
```json
{
  "retrieval_attempted": true,
  "context_injected": true,
  "intent_confidence": 0.72,
  "triggered_signals": ["keyword:investment", "temporal:last_year"],
  "context_block": {
    "xml_content": "<context>\n  <note title=\"Investment Review 2024\" path=\"finance/2024-review.md\" score=\"0.89\">\n    My portfolio grew by 12% in 2024 primarily due to...\n  </note>\n</context>",
    "sources": [
      {
        "note_path": "finance/2024-review.md",
        "note_title": "Investment Review 2024",
        "heading_context": "Annual Summary",
        "score": 0.89,
        "tags": ["#finance", "#annual-review"]
      }
    ],
    "total_chars": 312
  },
  "augmented_prompt": "[System: The following context was retrieved from the user's Obsidian knowledge base]\n<context>...</context>\n<instruction>...</instruction>\n\n[User]: What was my investment strategy last year?",
  "search_time_ms": 48.3
}
```

**Response — no personal context needed** (200):
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

**Errors**:

| Status | Body | Meaning |
|--------|------|---------|
| `422` | Pydantic validation detail | Invalid request parameters |
| `503` | `{"error_code": "AUGMENT_UNAVAILABLE", "message": "..."}` | Service not ready |

**Augmented prompt format**: The `augmented_prompt` field uses this structure when context is injected:
```
[System: The following context was retrieved from the user's Obsidian knowledge base]
<context>
  <note title="{title}" path="{path}" score="{score}">
    {content}
  </note>
</context>
<instruction>
  If the context above is relevant to the question, begin your response with
  "Based on your Obsidian notes..." and cite specific note titles.
  If the context is not relevant to the question, ignore it and respond normally.
</instruction>

[User]: {original_message}
```

### 2. Search Notes — `POST /search` (raw results)

Hybrid semantic + keyword search over indexed vault content. Returns ranked chunks with scores, related notes via wikilink graph traversal, and heading context.

**Request**:
```json
{
  "query": "database migration decision",
  "top_k": 5,
  "include_related": true,
  "threshold": 0.3
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `query` | string | *required* | Natural language search query |
| `top_k` | int | 5 | Number of results to return (1-20) |
| `include_related` | bool | true | Include related notes via wikilinks |
| `threshold` | float | 0.3 | Minimum similarity score filter |

**Response** (200):
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
  "related_notes": [
    {
      "note_path": "concepts/flyway.md",
      "note_title": "flyway",
      "relationship": "outgoing",
      "link_count": 1
    }
  ],
  "total_hits": 1,
  "search_time_ms": 45.2
}
```

**Errors**:

| Status | Body | Meaning |
|--------|------|---------|
| `422` | Pydantic validation detail | Invalid request parameters |
| `503` | `{"error_code": "SEARCH_UNAVAILABLE", "message": "..."}` | Index not ready |

### 3. Suggest Wikilinks — `POST /note/suggest-links`

Analyze draft note content and return suggested wikilinks (existing notes to link to), tags, and related notes from the indexed vault. Use this before writing a new note to the vault to discover connections.

**Request**:
```json
{
  "content": "Today I decided to use Flyway for database migrations because it supports versioned scripts...",
  "title": "Migration Strategy Decision",
  "max_suggestions": 5
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `content` | string | *required* | Draft note content (markdown) |
| `title` | string | null | Optional title for better semantic matching |
| `max_suggestions` | int | 5 | Maximum wikilink suggestions to return (1–20) |

**Response** (200):
```json
{
  "suggested_wikilinks": [
    {
      "display_text": "ADR-005: Database Migration Strategy",
      "target_path": "notes/adr-005.md",
      "score": 0.87
    }
  ],
  "suggested_tags": ["#database", "#architecture", "#decision"],
  "related_notes": [
    {
      "note_path": "concepts/flyway.md",
      "note_title": "flyway"
    }
  ]
}
```

**Errors**:

| Status | Body | Meaning |
|--------|------|---------|
| `422` | Pydantic validation detail | Invalid request parameters |
| `503` | `{"error_code": "SUGGEST_LINKS_UNAVAILABLE", "message": "..."}` | Service not ready |

### 4. Rebuild Index — `POST /index/rebuild`

Trigger a full re-index of all `.md` files in the vault. Deletes existing data and re-indexes from scratch. The file watcher automatically keeps the index updated after this.

**Request**: No body required.

**Response** (200):
```json
{
  "status": "success",
  "notes_indexed": 142,
  "chunks_created": 1087,
  "time_taken_seconds": 12.3
}
```

**Errors**:

| Status | Body | Meaning |
|--------|------|---------|
| `409` | `{"error_code": "REBUILD_IN_PROGRESS", "message": "..."}` | Rebuild already running |

### 5. Index Status — `GET /index/status`

Check the current state of the index: how many notes and chunks are indexed, whether the file watcher is active, and if Qdrant is reachable.

**Response** (200):
```json
{
  "indexed_notes": 142,
  "indexed_chunks": 1087,
  "last_indexed": "2025-02-15T10:30:00Z",
  "watcher_running": true,
  "qdrant_healthy": true
}
```

### 6. Note Links — `GET /note/{path}/links`

Get all outgoing wikilinks and backlinks for a specific note. Useful for graph exploration and understanding note relationships.

**Example**: `GET /note/notes/adr-005.md/links`

**Response** (200):
```json
{
  "note_path": "notes/adr-005.md",
  "outlinks": [
    {"note_path": "concepts/flyway.md", "note_title": "flyway"},
    {"note_path": "projects/backend-v2.md", "note_title": "backend-v2"}
  ],
  "backlinks": [
    {"note_path": "meetings/2025-01-15.md", "note_title": "2025-01-15"}
  ]
}
```

**Errors**:

| Status | Body | Meaning |
|--------|------|---------|
| `404` | `{"error_code": "NOTE_NOT_FOUND", "message": "..."}` | Note not in index |

### 7. Watcher Events — `GET /index/events`

List recent file watcher events (newest first). Useful for understanding what changes the watcher has detected and verifying that live indexing is working.

**Query Parameters**:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 50 | Number of events to return (1-100) |

**Example**: `GET /index/events?limit=10`

**Response** (200):
```json
{
  "events": [
    {
      "event_type": "modified",
      "file_path": "notes/adr-005.md",
      "timestamp": "2025-02-15T10:32:00Z",
      "dest_path": null
    },
    {
      "event_type": "moved",
      "file_path": "drafts/idea.md",
      "timestamp": "2025-02-15T10:31:00Z",
      "dest_path": "notes/idea.md"
    }
  ],
  "total": 2
}
```

Event types: `created`, `modified`, `deleted`, `moved`. The `dest_path` field is only populated for `moved` events.

### 8. Indexed Notes — `GET /index/notes`

List all notes currently in the index with their paths and titles. Useful for verifying index coverage and browsing available content.

**Request**: No parameters.

**Response** (200):
```json
{
  "notes": [
    {
      "note_path": "notes/adr-005.md",
      "note_title": "ADR-005: Database Migration Strategy"
    },
    {
      "note_path": "concepts/flyway.md",
      "note_title": "flyway"
    }
  ],
  "total": 2
}
```

### 9. Classify Intent — `POST /intent/classify`

Classify whether a user message requires personal knowledge retrieval. Returns a confidence score, triggered signal details, and an optional cleaned query. Useful for debugging the intent engine or building custom augmentation flows.

**Request**:
```json
{
  "message": "What was my investment strategy last year?"
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `message` | string | *required* | The user's message to classify |

**Response** (200):
```json
{
  "requires_personal_context": true,
  "confidence": 0.72,
  "triggered_signals": ["keyword:investment", "temporal:last_year"],
  "suggested_query": "investment strategy last year"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `requires_personal_context` | bool | Whether the message needs vault retrieval |
| `confidence` | float | Composite confidence score (0–1) |
| `triggered_signals` | list[str] | Signals that fired (e.g., `keyword:*`, `semantic`, `temporal:*`) |
| `suggested_query` | string \| null | Cleaned query with conversational prefixes stripped |

**Errors**: 422 (Pydantic validation detail — invalid parameters)

### 10. Vault Config — `GET /config/vault`

Resolve the vault name used for Obsidian URI deep links.

**Response** (200):
```json
{
  "vault_name": "my-obsidian-workspace",
  "is_configured": true,
  "message": null
}
```

When vault configuration cannot be resolved:
```json
{
  "vault_name": "",
  "is_configured": false,
  "message": "Obsidian deep links are unavailable. Set OBSIDIAN_VAULT_NAME or configure OBSIDIAN_VAULT_PATH to a valid vault directory."
}
```

| Field | Type | Description |
|-------|------|-------------|
| `vault_name` | string | Vault name to use in `obsidian://open` URIs |
| `is_configured` | bool | Whether deep links are currently usable |
| `message` | string or null | Optional user-facing troubleshooting guidance |

### 11. Health Check — `GET /health`

Verify the service is running.

**Response** (200):
```json
{
  "status": "ok",
  "timestamp": "2025-02-15T10:30:00Z"
}
```

## Error Responses

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

## Typical Query Patterns

### Proactive context augmentation (recommended)
```
POST /augment
{"message": "What was my investment strategy last year?"}
```
Returns an `augmented_prompt` with vault context already formatted for the LLM, or a pass-through response if no personal context is needed.

### Find information on a topic (raw results)
```
POST /search
{"query": "how does authentication work in our API"}
```

### Cite a past decision (raw results)
```
POST /search
{"query": "why did we choose PostgreSQL over MongoDB", "top_k": 3}
```

### Get wikilink suggestions before creating a note
```
POST /note/suggest-links
{"content": "...", "title": "My Draft Note"}
```

### Explore a note's neighborhood
```
GET /note/architecture/auth-system.md/links
```

### Check if the system is ready
```
GET /index/status
```
If `indexed_chunks` is 0, trigger a rebuild:
```
POST /index/rebuild
```

### Search without graph enrichment (faster)
```
POST /search
{"query": "deployment checklist", "include_related": false}
```

### Narrow results with higher threshold
```
POST /search
{"query": "kubernetes pod scheduling", "threshold": 0.5, "top_k": 3}
```
