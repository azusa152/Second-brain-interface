---
name: obsidian-knowledge-bridge
description: Search and retrieve context from the user's Obsidian vault. Augment prompts with personal knowledge, past decisions, and notes. Suggest wikilinks for new notes.
---

# Obsidian Knowledge Bridge

**Base URL**: `http://localhost:8000` (default; configurable via `SBI_API_PORT` in `.env`)

## When to Use

- User asks about their personal notes, decisions, or knowledge
- User references past events, projects, or their own documentation
- User wants to create a note worth preserving in their vault
- Use `POST /augment` for all routine queries — it auto-classifies intent and only retrieves context when relevant

## Constraints

- Index must be built first: `POST /index/rebuild` (one-time; watcher keeps it live after)
- Read-only vault: this service never modifies notes
- Local only: no external API calls

## Request Correlation

- You may send `X-Request-ID` on API calls for traceability.
- If omitted, the backend generates one and returns it in the response header.
- Reuse the same `X-Request-ID` across retries to simplify troubleshooting.

## Logging Environment

- `LOG_LEVEL` (`INFO` default): `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`
- `LOG_FORMAT` (`json` default): `json` for machine parsing, `console` for local readability
- `LOG_INCLUDE_QUERY_TEXT` (`false` default): keep disabled unless temporarily debugging sensitive query flows
- `DEBUG_ENDPOINTS` (`false` default): enables developer-only debug APIs (e.g. `POST /debug/tokenize`)

## Workflows

### A — Retrieve vault context (primary, use this by default)

1. `POST /augment` with `{"message": "<user message>"}`
2. If `context_injected: true` — prepend `augmented_prompt` to your LLM call
3. If `context_injected: false` — proceed without vault context

```json
POST /augment
{"message": "What was my investment strategy last year?", "top_k": 3}
```

Response when context found:
```json
{
  "retrieval_attempted": true,
  "context_injected": true,
  "intent_confidence": 0.72,
  "augmented_prompt": "[System: ...]\n<context>...</context>\n[User]: ...",
  "context_block": {"sources": [...], "total_chars": 312},
  "search_time_ms": 48.3
}
```

Response when no personal context needed:
```json
{"retrieval_attempted": false, "context_injected": false, "augmented_prompt": null}
```

### B — Raw search (when you need direct results)

1. `POST /search` with `{"query": "<query>", "top_k": 5}`
   - Response may include `did_you_mean` when typo-correction fallback is used after an initial no-hit search.
   - Each result includes `highlights`; use these snippets in UI before raw `content`.
2. If you want to open a result in Obsidian, call `GET /config/vault` and build:
   `obsidian://open?vault=<vault_name>&file=<note_path_without_md>`
3. If `/config/vault` returns `is_configured: false`, show the returned `message`
   and ask the user to set `OBSIDIAN_VAULT_NAME` (or fix `OBSIDIAN_VAULT_PATH`).

```json
POST /search
{"query": "database migration decision", "top_k": 5}
```

### C — Create a note in the vault

1. Draft the note content in markdown
2. `POST /note/suggest-links` with `{"content": "...", "title": "..."}` — get wikilink + tag suggestions
3. Write `.md` file to vault with frontmatter template below, incorporating suggestions
4. Service auto-indexes the new note within 5 seconds

```json
POST /note/suggest-links
{"content": "...", "title": "My Draft Note Title"}
```

Response:
```json
{
  "suggested_wikilinks": [
    {"display_text": "ADR-005: DB Strategy", "target_path": "notes/adr-005.md", "score": 0.87}
  ],
  "suggested_tags": ["#architecture", "#decision"],
  "related_notes": [{"note_path": "concepts/flyway.md", "note_title": "flyway"}]
}
```

Frontmatter template for new notes:
```yaml
---
title: "{title}"
date: "{YYYY-MM-DD}"
tags: [{suggested_tags}]
created_by: openclaw
---
```

**What is worth preserving as a note:**
- Decisions made and their reasoning
- Key insights or discoveries
- Meeting summaries and action items
- Useful references or comparisons
- Project plans or architecture decisions

**Not worth preserving:**
- Trivial questions or small talk
- Information already in existing notes
- Temporary or ephemeral context

**Folder convention:** Write new notes to `inbox/` unless a more specific folder is obvious.

**If suggest-links is unavailable (503):** Write the note without suggestions — it will still be indexed.

## Quick Reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/augment` | **Primary** — classify intent, retrieve context, return augmented prompt |
| `POST` | `/search` | Hybrid semantic + keyword search (raw results) |
| `GET` | `/config/vault` | Resolve vault name for Obsidian URI deep links |
| `POST` | `/note/suggest-links` | Suggest wikilinks and tags for draft note content |
| `POST` | `/index/rebuild` | Trigger full vault re-index |
| `GET` | `/index/status` | Index health and statistics |
| `GET` | `/index/events` | Recent file watcher events |
| `GET` | `/index/notes` | List all indexed notes |
| `GET` | `/note/{path}/links` | Backlinks and outlinks for a note |
| `POST` | `/intent/classify` | Standalone intent classification |
| `POST` | `/debug/tokenize` | Tokenizer diagnostics for CJK edge-case troubleshooting (`DEBUG_ENDPOINTS=true`) |
| `GET` | `/health` | Service health check |

## Error Handling

| Status | Meaning | Action |
|--------|---------|--------|
| `503` | Service not ready | Run `POST /index/rebuild`, then retry |
| `409` | Rebuild already running | Wait for rebuild to complete |
| `404` | Note not found in index | Check `GET /index/notes` for indexed paths |
| `422` | Invalid request parameters | Check request body against API reference |

For full request/response schemas, see [API_REFERENCE.md](API_REFERENCE.md).
