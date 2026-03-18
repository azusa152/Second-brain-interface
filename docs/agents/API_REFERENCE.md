# OpenClaw-Obsidian Knowledge Bridge — Full API Reference

**Base URL**: `http://localhost:8000` (default; configurable via `SBI_API_PORT` in `.env`)

> For the compact agent skill, see [SKILL.md](SKILL.md). For search filter details, see [SEARCH_FILTERS.md](SEARCH_FILTERS.md). For service management and debugging, see [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md).

## Endpoints

> **Recommended primary endpoint**: Use `POST /augment` for most agent interactions.
> It classifies intent, retrieves context when needed, and returns a ready-to-inject prompt —
> all in one call. Use `POST /search` only when you need raw search results without prompt formatting.

### 1. Augment Prompt — `POST /augment` ⭐ Recommended

Classify intent, retrieve relevant vault context when needed, and return a fully assembled augmented prompt ready for LLM injection.

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
  "augmented_prompt": "[System: ...]\n<context>...</context>\n<instruction>...</instruction>\n\n[User]: What was my investment strategy last year?",
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

**Augmented prompt format** (when `context_injected: true`):
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

**Errors**:

| Status | Body | Meaning |
|--------|------|---------|
| `422` | Pydantic validation detail | Invalid request parameters |
| `503` | `{"error_code": "AUGMENT_UNAVAILABLE", "message": "..."}` | Service not ready |

### 2. Search Notes — `POST /search`

Hybrid semantic + keyword search over indexed vault content. If no hits on the original query, may retry with typo-correction and return `did_you_mean`. Response includes ranked chunks, related notes via wikilink graph traversal, and heading context.

**Request**:
```json
{
  "query": "database migration decision",
  "top_k": 5,
  "include_related": true,
  "threshold": 0.3,
  "filters": {
    "tags": ["#architecture"],
    "path_prefix": "projects/",
    "modified_after": "2025-01-01T00:00:00Z"
  }
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `query` | string | *required* | Natural language search query |
| `top_k` | int | 5 | Number of results to return (1–20) |
| `include_related` | bool | true | Include related notes via wikilinks |
| `threshold` | float | 0.3 | Minimum similarity score filter |
| `filters` | object | null | Metadata filters — see [SEARCH_FILTERS.md](SEARCH_FILTERS.md) |

**Response** (200):
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
      "link_count": 1
    }
  ],
  "total_hits": 1,
  "search_time_ms": 45.2,
  "applied_filters": {
    "tags": ["#architecture"],
    "path_prefix": "projects/",
    "modified_after": "2025-01-01T00:00:00Z"
  }
}
```

**Errors**:

| Status | Body | Meaning |
|--------|------|---------|
| `409` | `{"error_code": "INDEX_REBUILD_REQUIRED", "message": "..."}` | `path_prefix` used but index lacks prefix data — run `POST /index/rebuild` |
| `422` | Pydantic validation detail | Invalid request parameters |
| `503` | `{"error_code": "SEARCH_UNAVAILABLE", "message": "..."}` | Index not ready |

### 3. Suggest Wikilinks — `POST /note/suggest-links`

Analyze draft note content and return suggested wikilinks, tags, and related notes.

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
| `max_suggestions` | int | 5 | Maximum wikilink suggestions (1–20) |

**Response** (200):
```json
{
  "suggested_wikilinks": [
    {"display_text": "ADR-005: Database Migration Strategy", "target_path": "notes/adr-005.md", "score": 0.87}
  ],
  "suggested_tags": ["#database", "#architecture", "#decision"],
  "related_notes": [
    {"note_path": "concepts/flyway.md", "note_title": "flyway"}
  ]
}
```

**Errors**:

| Status | Body | Meaning |
|--------|------|---------|
| `422` | Pydantic validation detail | Invalid request parameters |
| `503` | `{"error_code": "SUGGEST_LINKS_UNAVAILABLE", "message": "..."}` | Service not ready |

### 4. Rebuild Index — `POST /index/rebuild`

Full re-index of all `.md` files. Deletes existing data and re-indexes from scratch. File watcher keeps the index updated after this.

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

Check index state: note/chunk counts, watcher status, and Qdrant health.

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

Get outgoing wikilinks and backlinks for a note.

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

### 7. Indexed Notes — `GET /index/notes`

List all notes in the index with paths and titles.

**Response** (200):
```json
{
  "notes": [
    {"note_path": "notes/adr-005.md", "note_title": "ADR-005: Database Migration Strategy"},
    {"note_path": "concepts/flyway.md", "note_title": "flyway"}
  ],
  "total": 2
}
```

### 8. Vault Config — `GET /config/vault`

Resolve the vault name for Obsidian URI deep links.

**Response** (200):
```json
{"vault_name": "my-obsidian-workspace", "is_configured": true, "message": null}
```

When vault configuration cannot be resolved:
```json
{
  "vault_name": "",
  "is_configured": false,
  "message": "Obsidian deep links are unavailable. Set OBSIDIAN_VAULT_NAME or configure OBSIDIAN_VAULT_PATH to a valid vault directory."
}
```

## Error Responses

All error responses share a consistent JSON body:

```json
{"error_code": "SEARCH_UNAVAILABLE", "message": "Human-readable description of the error."}
```

| Status | `error_code` | Meaning |
|--------|-------------|---------|
| `409` | `REBUILD_IN_PROGRESS` | A rebuild is already running |
| `409` | `INDEX_REBUILD_REQUIRED` | Index needs rebuild for requested filter |
| `404` | `NOTE_NOT_FOUND` | Requested note is not in the index |
| `503` | `*_UNAVAILABLE` | A backend service is not ready |
| `500` | `INTERNAL_SERVER_ERROR` | Unexpected server error |
