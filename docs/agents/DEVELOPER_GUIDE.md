# Developer Guide — Obsidian Knowledge Bridge

> For the agent skill reference, see [SKILL.md](SKILL.md). For full API schemas, see [API_REFERENCE.md](API_REFERENCE.md).

## Service Management

| Command | Description |
|---------|-------------|
| `make up` | Start all services (backend + Qdrant), rebuilding images |
| `make down` | Stop all services |
| `make restart` | Stop, rebuild, and restart all services |
| `make logs` | Tail logs from all running services (stdout, via Docker) |
| `make logs-backend` | Tail backend logs only (stdout) |
| `make logs-file` | Tail the current log file on the host (`logs/sbi.log`) |
| `make build` | Build Docker images without starting |

Use `make restart` after code changes or when the service is unhealthy.

## Request Correlation

- Send `X-Request-ID` on API calls to correlate logs across layers.
- If omitted, the backend generates one and returns it in the response header.
- Reuse the same `X-Request-ID` across retries to simplify troubleshooting.

## Logging Environment

| Variable | Default | Values |
|----------|---------|--------|
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `LOG_FORMAT` | `json` | `json` (machine parsing), `console` (local readability) |
| `LOG_INCLUDE_QUERY_TEXT` | `false` | Keep disabled unless temporarily debugging query flows |
| `DEBUG_ENDPOINTS` | `false` | Enables developer-only debug APIs (e.g. `POST /debug/tokenize`) |
| `LOG_FILE_ENABLED` | `true` | Write JSON logs to a file in addition to stdout |
| `LOG_DIR` | `/app/logs` | Log directory inside the container (bind-mounted to `./logs/` on host) |

## Log Files

When `LOG_FILE_ENABLED=true` (default in Docker), structured JSON logs are written to
`./logs/sbi.log` on the host. The file rotates daily at UTC midnight; last 3 days are kept.

```
logs/
  sbi.log              # active file for the current day
  sbi.log.2026-03-22   # yesterday
  sbi.log.2026-03-21   # 2 days ago
  sbi.log.2026-03-20   # 3 days ago (oldest; older files auto-deleted)
```

**Useful queries:**

```bash
# Stream the live log file
make logs-file

# Filter for errors
make logs-search QUERY='select(.level=="error")'

# Trace a specific request by ID
cat logs/sbi.log | jq 'select(.request_id=="<id>")'

# Summarise event counts by level
cat logs/sbi.log | jq -s 'group_by(.level) | map({level: .[0].level, count: length})'
```

## Debug Tokenizer — `POST /debug/tokenize`

Inspect CJK sparse tokenization behavior. Returns normalization, segmentation, and token-level POS decisions. Only available when `DEBUG_ENDPOINTS=true`; returns `404` otherwise.

**Request**:
```json
{"text": "ＡＩ設計について"}
```

**Response** (200):
```json
{
  "original": "ＡＩ設計について",
  "normalized": "AI設計について",
  "sanitized": "AI設計について",
  "detected_language": "japanese",
  "segments": [
    {"text": "AI", "is_cjk": false, "language": "other"},
    {"text": "設計について", "is_cjk": true, "language": "japanese"}
  ],
  "sparse_output": "AI 設計",
  "tokens": [
    {"surface": "設計", "pos": "名詞", "kept": true, "language": "japanese", "normalized": "設計"},
    {"surface": "について", "pos": "助詞", "kept": false, "language": "japanese", "normalized": "について"}
  ]
}
```

| Status | Meaning |
|--------|---------|
| `404` | Debug endpoints disabled (`DEBUG_ENDPOINTS=false`) |
| `422` | Invalid request body |

## Dashboard — `GET /`

The root URL redirects to the monitoring dashboard with a `307 Temporary Redirect`. Both entry points are equivalent:

- `http://localhost:8000/` → redirects to `/dashboard/`
- `http://localhost:8000/dashboard/` → serves the dashboard directly

The dashboard is only available when the `frontend/` directory is present (always true in the Docker image; may be absent in bare backend runs).

## Health Check — `GET /health`

Verify the service is running.

```json
{"status": "ok", "timestamp": "2025-02-15T10:30:00Z"}
```

## Watcher Events — `GET /index/events`

List recent file watcher events (newest first). Useful for verifying live indexing.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 50 | Events to return (1–100) |

Event types: `created`, `modified`, `deleted`, `moved`. The `dest_path` field is only populated for `moved` events.

## Intent Classification — `POST /intent/classify`

Standalone intent classification for debugging or custom augmentation flows.

**Request**: `{"message": "What was my investment strategy last year?"}`

**Response**:
```json
{
  "requires_personal_context": true,
  "confidence": 0.72,
  "triggered_signals": ["keyword:investment", "temporal:last_year"],
  "suggested_query": "investment strategy last year"
}
```
