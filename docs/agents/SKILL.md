# OpenClaw-Obsidian Knowledge Bridge — Agent Skill

## Overview

This skill gives OpenClaw semantic search and graph traversal over the user's Obsidian vault. Use it to find relevant notes, cite past decisions, retrieve technical documentation, and explore note relationships — all without manual context switching.

**Base URL**: `http://localhost:8000` (default; configurable via `SBI_API_PORT` in `.env`)

## Constraints

- **Read-only vault**: The middleware never modifies Obsidian notes. All operations are read-only.
- **Index must be built first**: Before searching, trigger a full index rebuild via `POST /index/rebuild`. The file watcher keeps the index updated after the initial build.
- **Local only**: All processing (embedding, indexing, search) happens on the user's machine. No external API calls.

## Available Endpoints

### 1. Search Notes — `POST /search`

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
      "highlights": []
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

**Errors**: 422 (invalid parameters), 503 (index not ready)

### 2. Rebuild Index — `POST /index/rebuild`

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

**Errors**: 409 (rebuild already in progress)

### 3. Index Status — `GET /index/status`

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

### 4. Note Links — `GET /note/{path}/links`

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

**Errors**: 404 (note not in index)

### 5. Watcher Events — `GET /index/events`

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

### 6. Indexed Notes — `GET /index/notes`

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

### 7. Health Check — `GET /health`

Verify the service is running.

**Response** (200):
```json
{
  "status": "ok",
  "timestamp": "2025-02-15T10:30:00Z"
}
```

## Typical Query Patterns

### Find information on a topic
```
POST /search
{"query": "how does authentication work in our API"}
```

### Cite a past decision
```
POST /search
{"query": "why did we choose PostgreSQL over MongoDB", "top_k": 3}
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
