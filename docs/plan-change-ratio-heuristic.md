# Plan: Change-Ratio Heuristic for Incremental Rebuild

**Version:** 1.0  
**Status:** Implemented — branch `001-change-ratio-heuristic`  
**Author:** AI Architect  
**Last Updated:** 2026-05-21  
**Reference:** [ObsidianRAG by Vasallo94](https://github.com/Vasallo94/ObsidianRAG)

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Design Decision](#2-design-decision)
3. [Component Design](#3-component-design)
4. [Data Flow](#4-data-flow)
5. [Configuration](#5-configuration)
6. [Affected Files](#6-affected-files)
7. [Tests](#7-tests)
8. [Verification](#8-verification)

---

## 1. Problem Statement

The current incremental rebuild always processes every changed file individually via sequential Qdrant upserts. When a large portion of the vault changes at once (e.g. bulk rename, vault migration, or first sync after a long offline period), the incremental path becomes:

- **Slower** than a clean full rebuild due to per-file delete + upsert overhead
- **Noisier** in logs — hundreds of individual file events instead of one rebuild event
- **Inconsistent** — partial progress is visible between upserts

A full rebuild clears the collection and bulk-inserts everything, which is faster for large diffs and leaves the index in a deterministic state.

---

## 2. Design Decision

Before executing any Qdrant writes during an incremental rebuild, compute a **change ratio**:

```
ratio = (changed_files + deleted_files) / total_vault_files
```

If `ratio > threshold` (default `0.30`), abort the incremental path and delegate to `rebuild_index()`.

**Key properties:**
- Threshold is configurable via environment variable
- The decision is logged as a structured event before switching
- The rebuild lock is released before calling `rebuild_index()` to avoid deadlock (rebuild acquires its own lock)
- At `ratio == threshold` the incremental path is kept (threshold is exclusive)

---

## 3. Component Design

### 3.1 `IndexService` — Two-Phase Incremental Rebuild

The current incremental loop discovers changes and writes to Qdrant in a single pass. This must be split into two phases to allow the ratio check between them.

```
Phase 1 — Discovery (pure I/O, no Qdrant writes)
  ├── Walk vault, read file content, compute SHA-256 hashes
  ├── Compare each hash against HashRegistry
  ├── Build: to_reindex: list[tuple[abs_path, rel_path, new_hash]]
  └── Build: to_delete: set[str]   (known_paths − vault_paths)

Ratio Check
  ├── total_changed = len(to_reindex) + len(to_delete)
  ├── ratio = total_changed / total_files  (skip if total_files == 0)
  ├── If ratio > threshold:
  │     emit structured log: change_ratio_exceeded
  │     release rebuild lock
  │     call self.rebuild_index()
  │     return
  └── Else: proceed to Phase 2

Phase 2 — Qdrant Writes (existing logic, now iterates to_reindex / to_delete)
  ├── For each (abs_path, rel_path, new_hash) in to_reindex:
  │     delete old chunks by note_path
  │     parse + chunk + embed + upsert
  │     update HashRegistry
  └── For each stale_path in to_delete:
        delete chunks by note_path
        remove from HashRegistry
```

### 3.2 Constructor Change

```python
class IndexService:
    def __init__(
        self,
        ...,
        incremental_rebuild_ratio_threshold: float = INCREMENTAL_REBUILD_RATIO_THRESHOLD,
    ) -> None:
        ...
        self._rebuild_ratio_threshold = incremental_rebuild_ratio_threshold
```

### 3.3 Structured Log Event

Emitted when the ratio check triggers a full rebuild:

```json
{
  "event": "change_ratio_exceeded",
  "ratio": 0.42,
  "threshold": 0.30,
  "changed": 42,
  "total": 100,
  "triggering_full_rebuild": true
}
```

---

## 4. Data Flow

```
incremental_rebuild() called
        │
        ▼
Phase 1: walk vault files
        │
        ├─ compute hash per file
        ├─ diff against HashRegistry
        └─ collect to_reindex, to_delete
        │
        ▼
Ratio check
  ratio = (len(to_reindex) + len(to_delete)) / total_files
        │
   ratio > threshold?
   ┌────┴────┐
  YES        NO
   │          │
   ▼          ▼
log event   Phase 2: Qdrant writes
release lock
rebuild_index()
return
```

---

## 5. Configuration

### `backend/domain/constants.py`

```python
INCREMENTAL_REBUILD_RATIO_THRESHOLD: float = 0.30
```

### `backend/config.py` (pydantic-settings)

```python
incremental_rebuild_ratio_threshold: float = Field(
    default=0.30,
    description="If changed+deleted files exceed this fraction of the vault, "
                "switch from incremental to full rebuild.",
)
```

Environment variable: `SBI_INCREMENTAL_REBUILD_RATIO_THRESHOLD`

---

## 6. Affected Files

| File | Change |
|---|---|
| `backend/domain/constants.py` | Add `INCREMENTAL_REBUILD_RATIO_THRESHOLD = 0.30` |
| `backend/config.py` | Add `incremental_rebuild_ratio_threshold: float` field |
| `backend/application/index_service.py` | Refactor incremental loop into Phase 1 + ratio check + Phase 2; add constructor param |
| `backend/api/dependencies.py` | Pass `settings.incremental_rebuild_ratio_threshold` to `IndexService` |

No API contract changes. No new dependencies.

---

## 7. Tests

### New test class in `tests/test_index_service.py`: `TestChangeRatioHeuristic`

| Test | Scenario | Expected |
|---|---|---|
| `test_high_ratio_triggers_full_rebuild` | 4/10 files changed (ratio=0.4 > 0.3) | `rebuild_index()` called; incremental upsert not called |
| `test_low_ratio_stays_incremental` | 2/10 files changed (ratio=0.2 < 0.3) | `rebuild_index()` not called; upsert called |
| `test_boundary_ratio_stays_incremental` | 3/10 files changed (ratio=0.3 == threshold) | `rebuild_index()` not called (exclusive threshold) |
| `test_custom_threshold` | Custom threshold=0.5; 4/10 changed (ratio=0.4 < 0.5) | Stays incremental |
| `test_empty_vault_no_crash` | 0 total files | No division-by-zero; no rebuild triggered |

---

## 8. Verification

1. Create a test vault with 10 notes; run a full rebuild to populate the index.
2. Modify 4 notes (ratio = 0.4, above default threshold of 0.3).
3. Trigger incremental rebuild (`POST /index/rebuild` or wait for watcher).
4. Check structured logs for `change_ratio_exceeded` event with correct ratio/threshold values.
5. Confirm the subsequent `rebuild_complete` log appears (full rebuild ran).
6. Repeat with only 2 notes changed (ratio = 0.2); verify no `change_ratio_exceeded` event and only `incremental_rebuild_completed` in logs.
