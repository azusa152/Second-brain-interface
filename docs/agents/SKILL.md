---
name: obsidian-knowledge-bridge
description: >
  Retrieve personal context from the user's Obsidian vault to augment LLM
  prompts with their notes, past decisions, and documentation. Use when the
  user references their own knowledge, projects, meetings, or past work —
  even if they don't mention "notes" or "Obsidian" explicitly. Also use to
  suggest wikilinks and tags when creating new vault notes. Do not use for
  general knowledge questions unrelated to the user's personal notes.
---

# Obsidian Knowledge Bridge

**Base URL**: `http://localhost:8000`

## When to Use

- User asks about their personal notes, decisions, or knowledge
- User references past events, projects, or their own documentation
- User wants to create a note worth preserving in their vault
- Default to `POST /augment` — it auto-classifies intent and only retrieves when relevant

## Constraints

- Index must be built first: `POST /index/rebuild` (one-time; watcher keeps it live after)
- Read-only vault: this service never modifies notes
- Local only: no external API calls

## Workflows

### A — Retrieve vault context (primary)

1. `POST /augment` with `{"message": "<user message>"}`
2. If `context_injected: true` — prepend `augmented_prompt` to your LLM call
3. If `context_injected: false` — proceed without vault context

### B — Raw search (when you need direct results)

1. `POST /search` with `{"query": "<query>", "top_k": 5}`
   - Optional `filters`: `tags`, `exclude_tags`, `path_prefix`, `modified_after`/`modified_before`. See [SEARCH_FILTERS.md](SEARCH_FILTERS.md).
   - Response may include `did_you_mean` on typo-correction fallback.
2. Build Obsidian deep links: `GET /config/vault` then `obsidian://open?vault=<vault_name>&file=<note_path_without_md>`

### C — Create a note in the vault

1. Draft the note content in markdown
2. `POST /note/suggest-links` with `{"content": "...", "title": "..."}` — returns `suggested_wikilinks`, `suggested_tags`, `related_notes`
3. Write `.md` file to vault with frontmatter below, incorporating suggestions
4. Service auto-indexes the new note within 5 seconds

```yaml
---
title: "{title}"
date: "{YYYY-MM-DD}"
tags: [{suggested_tags}]
created_by: openclaw
---
```

**Worth preserving:** decisions and reasoning, key insights, meeting summaries, useful references, architecture decisions.
**Not worth preserving:** trivial questions, info already in existing notes, ephemeral context.
**Folder convention:** write to `inbox/` unless a more specific folder is obvious.
**If suggest-links returns 503:** write the note without suggestions — it will still be indexed.

## Quick Reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/augment` | **Primary** — classify intent, retrieve context, return augmented prompt |
| `POST` | `/search` | Hybrid semantic + keyword search (raw results) |
| `POST` | `/note/suggest-links` | Suggest wikilinks and tags for draft note content |
| `GET` | `/config/vault` | Resolve vault name for Obsidian URI deep links |
| `POST` | `/index/rebuild` | Trigger full vault re-index |
| `GET` | `/index/status` | Index health and statistics |
| `GET` | `/index/notes` | List all indexed notes |
| `GET` | `/note/{path}/links` | Backlinks and outlinks for a note |

## Error Handling

| Status | Meaning | Action |
|--------|---------|--------|
| `503` | Service not ready | Run `POST /index/rebuild`, then retry |
| `409` | Rebuild already running / index rebuild required | Wait or rebuild index |
| `404` | Note not found in index | Check `GET /index/notes` for indexed paths |
| `422` | Invalid request parameters | Check request body against API reference |

For full request/response schemas, see [API_REFERENCE.md](API_REFERENCE.md).
For search filter details, see [SEARCH_FILTERS.md](SEARCH_FILTERS.md).
For service management and debugging, see [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md).
