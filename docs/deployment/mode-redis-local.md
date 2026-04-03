# Execution Mode: `redis` / `mode: local`

Redis-backed execution where the API process itself spawns asyncio worker
tasks to drain the queue. Redis is required (run via Docker) but no external
worker processes or Kubernetes are needed.

This is the **recommended development mode** when you need retry + DLQ
semantics but are not yet deploying to Kubernetes.

---

## When to use

| Situation | Recommendation |
|---|---|
| Local development with retry/DLQ | ✅ Best choice |
| Single-node production with persistence | ✅ Suitable |
| Need batch state to survive API restart | ✅ |
| Want to mirror production Redis schema locally | ✅ |
| Need workers on separate machines | ❌ Use `redis/worker` mode |
| Need true scale-to-zero | ❌ Use `redis/worker` mode |

---

## How it differs from `local` mode

| Concern | `local` | `redis` / `mode: local` |
|---|---|---|
| Retry on failure | No | Yes (3× exponential backoff) |
| Dead Letter Queue | No | Yes (`pipeline:dlq:{batch_id}`) |
| Batch state on restart | Lost | Persisted in Redis |
| In-flight visibility | In-memory set | Redis SET (`pipeline:inflight:{id}`) |
| External infra | None | Redis (Docker, 128 MB) |
| Worker location | Same process | Same process (asyncio tasks) |

---

## Configuration

```yaml
# src/pipeline/presets/composable-redis.yaml
execution:
  backend: redis
  concurrency: 4         # asyncio worker tasks spawned per submit()
  timeout: 3600
  redis:
    host: localhost       # override with REDIS_HOST
    port: 6379
    mode: local           # ← this is what makes it local mode
    max_retries: 3
    retry_backoff_base: 1.0    # seconds
    retry_backoff_max: 60.0    # cap
    result_ttl: 3600           # seconds to keep results in Redis
```

Or via environment variables:

```bash
PIPELINE_EXECUTION_BACKEND=redis
REDIS_HOST=localhost
REDIS_WORKER_MODE=local
PIPELINE_EXECUTION_CONCURRENCY=4
REDIS_MAX_RETRIES=3
```

---

## Architecture

```
API process
  └── PipelineService
        └── RedisBackend (mode=local)
              │
              ├── submit([files])
              │     ├── RPUSH pipeline:queue × N items
              │     ├── HSET pipeline:meta:{batch_id} total=N
              │     └── spawn N asyncio Tasks (_worker_loop)
              │
              └── asyncio Tasks (concurrency=4)
                    ├── BLPOP pipeline:queue (5s timeout)
                    ├── pipeline.run(file)
                    │     ├── success  → HSET pipeline:results:{id}
                    │     ├── retry    → sleep(backoff) → RPUSH queue
                    │     └── DLQ      → RPUSH pipeline:dlq:{id}
                    └── exit when queue empty
```

---

## Starting the stack

### Option A — Redis in Docker, API locally

```bash
# 1. Start Redis
docker run -d --name openrag-redis -p 6379:6379 redis:7-alpine \
  redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru --save ""

# 2. Run the API
PIPELINE_EXECUTION_BACKEND=redis \
REDIS_HOST=localhost \
REDIS_WORKER_MODE=local \
PIPELINE_CONFIG_FILE=src/pipeline/presets/composable-redis.yaml \
uv run uvicorn api.main:app --reload --port 8000
```

### Option B — docker-compose

```bash
docker compose --profile redis up opensearch openrag-backend redis
```

The `openrag-backend` service picks up `REDIS_HOST=redis` from the compose
env block automatically.

---

## Testing

### 1. Submit a file

```bash
BATCH=$(curl -sX POST http://localhost:8000/api/v1/pipeline/upload \
  -F "files=@/path/to/document.pdf" | jq -r .batch_id)
echo "Batch: $BATCH"
```

### 2. Watch the queue drain in real time

```bash
# Terminal 2 — watch queue depth drop to 0
watch -n1 'docker exec openrag-redis redis-cli LLEN pipeline:queue'
```

### 3. Check progress

```bash
curl http://localhost:8000/api/v1/pipeline/status/$BATCH | jq
```

### 4. Inspect Redis keys directly

```bash
R="docker exec openrag-redis redis-cli"

$R HGETALL pipeline:meta:$BATCH       # total, submitted_at
$R HGETALL pipeline:results:$BATCH    # file_hash → result JSON
$R LRANGE  pipeline:dlq:$BATCH 0 -1  # permanently failed items
$R SMEMBERS pipeline:inflight:$BATCH  # currently processing
```

### 5. Test retry behaviour

```bash
# Simulate transient failure: stop OpenSearch
docker stop os

# Submit — will fail, be retried up to 3×, then go to DLQ
BATCH=$(curl -sX POST http://localhost:8000/api/v1/pipeline/upload \
  -F "files=@/path/to/document.pdf" | jq -r .batch_id)

# Watch retry counter climb in queue item
docker exec openrag-redis redis-cli LRANGE pipeline:queue 0 -1

# Restart OpenSearch before retries exhaust to see recovery
docker start os

# Final status
curl http://localhost:8000/api/v1/pipeline/status/$BATCH | jq .failed
# → 0 if OpenSearch came back before retries exhausted
```

### 6. Test DLQ (all retries exhausted)

```bash
# Keep OpenSearch stopped — let all 3 retries exhaust
docker stop os
BATCH=$(curl -sX POST http://localhost:8000/api/v1/pipeline/upload \
  -F "files=@/path/to/document.pdf" | jq -r .batch_id)

# Wait for 1s + 2s + 4s = 7s of backoff + processing time
sleep 15

# Confirm DLQ entry
docker exec openrag-redis redis-cli LRANGE pipeline:dlq:$BATCH 0 -1
# → [{"file": {...}, "error": "...", "attempts": 4}]

# Status shows failed + DLQ prefix
curl http://localhost:8000/api/v1/pipeline/status/$BATCH | jq '.results[].error'
# → "[DLQ after 4 attempt(s)] ConnectionError: ..."

docker start os
```

### 7. Test batch survival across API restart

```bash
# Submit a large batch
BATCH=$(curl -sX POST http://localhost:8000/api/v1/pipeline/upload \
  -F "files=@doc1.pdf" -F "files=@doc2.pdf" -F "files=@doc3.pdf" \
  | jq -r .batch_id)

# Kill the API process mid-batch
pkill -f uvicorn

# Check Redis — meta and results are still there
docker exec openrag-redis redis-cli HGETALL pipeline:meta:$BATCH

# Restart API
uv run uvicorn api.main:app --reload &

# In local mode, orphaned queue items are NOT automatically re-consumed
# (workers were asyncio tasks that died with the process).
# Unprocessed items remain in pipeline:queue for manual inspection.
# Switch to redis/worker mode for true crash recovery.
docker exec openrag-redis redis-cli LLEN pipeline:queue
```

### 8. Test cancellation

```bash
BATCH=$(curl -sX POST http://localhost:8000/api/v1/pipeline/upload \
  -F "files=@doc1.pdf" -F "files=@doc2.pdf" | jq -r .batch_id)

# Cancel immediately
curl -X DELETE http://localhost:8000/api/v1/pipeline/status/$BATCH

# Workers check the cancelled flag before each file
docker exec openrag-redis redis-cli GET pipeline:cancelled:$BATCH
# → "1"
```

---

## Failure behaviour

| Scenario | Outcome |
|---|---|
| Network timeout (OpenAI, OpenSearch) | Retry up to `max_retries` with backoff → DLQ |
| Corrupt / unreadable file | `status="failed"` (no retry — not transient) |
| No chunks produced | `status="skipped"` |
| All retries exhausted | Moved to `pipeline:dlq:{batch_id}`, surfaced in `get_progress()` |
| API process restart | Queue items remain in Redis; asyncio workers gone — items wait for next submit or manual re-run |

---

## Key Redis keys

```
pipeline:queue                  Global work queue (RPUSH / BLPOP)
pipeline:meta:{batch_id}        Batch metadata (total, submitted_at)
pipeline:inflight:{batch_id}    Files currently processing (SET)
pipeline:results:{batch_id}     Completed results (HASH file_hash → JSON)
pipeline:dlq:{batch_id}         Dead letter queue (LIST)
pipeline:cancelled:{batch_id}   Cancellation flag (STRING "1")
```

All keys expire after `result_ttl` seconds (default 3600).
