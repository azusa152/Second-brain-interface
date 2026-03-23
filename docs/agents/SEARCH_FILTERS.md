# Search Filters Reference

> For the full `POST /search` schema, see [API_REFERENCE.md](API_REFERENCE.md). For the agent skill, see [SKILL.md](SKILL.md).

## Filter Fields

Pass these inside the `filters` object of `POST /search`:

| Field | Type | Description |
|-------|------|-------------|
| `tags` | list[str] | Include notes matching **any** listed tag (e.g. `["#architecture"]`) |
| `exclude_tags` | list[str] | Exclude notes matching **any** listed tag |
| `path_prefix` | string | Scope to notes under a folder prefix (strict `startswith` match) |
| `modified_after` | datetime | Only notes modified **on or after** this timestamp (ISO 8601) |
| `modified_before` | datetime | Only notes modified **before** this timestamp (ISO 8601) |

All fields are optional. Combine freely — they are ANDed together.

## `path_prefix` Semantics

- Uses strict folder-prefix matching: `projects/` matches `projects/infra/plan.md` but **not** `personal/projects-notes.md`.
- Requires the `note_path_prefixes` payload field in the index. If the index was built before this feature, the API returns **409** (`INDEX_REBUILD_REQUIRED`).
- **Fix**: run `POST /index/rebuild` to re-index with prefix data, then retry.

## Date Range Validation

- `modified_after` must be before `modified_before` when both are specified.
- Dates must be ISO 8601 format (e.g. `2025-01-01T00:00:00Z`).
- Invalid ranges return **422** with Pydantic validation details.

## Examples

Scope to a folder with tag filter:
```json
{"query": "auth design", "filters": {"tags": ["#architecture"], "path_prefix": "projects/"}}
```

Recent notes only:
```json
{"query": "meeting action items", "filters": {"modified_after": "2025-06-01T00:00:00Z"}}
```

Exclude archived notes:
```json
{"query": "deployment checklist", "filters": {"exclude_tags": ["#archive"]}}
```
