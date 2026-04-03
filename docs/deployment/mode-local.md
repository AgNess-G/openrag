# Execution Mode: `local`

The simplest execution mode. The pipeline runs entirely in-process using
`asyncio.Semaphore` to limit concurrency. No external services required
beyond OpenSearch.

---

## When to use

| Situation | Recommendation |
|---|---|
| Local development | ✅ Default choice |
| Single-node production, low volume | ✅ Suitable |
| CI / automated testing | ✅ Zero infra |
| Need retry + DLQ | ❌ Use `redis` mode |
| Need scale-to-zero in Kubernetes | ❌ Use `redis` mode |
| > 50k documents / day | ❌ Use `redis` mode |

---

## Configuration

```yaml
# src/pipeline/presets/composable-basic.yaml (default)
execution:
  backend: local
  concurrency: 4     # parallel files in-process (1–64)
  timeout: 3600      # seconds before a batch times out
```

Or via environment variables:

```bash
PIPELINE_EXECUTION_BACKEND=local
PIPELINE_EXECUTION_CONCURRENCY=4
PIPELINE_EXECUTION_TIMEOUT=3600
```

---

## How it works

```
PipelineService.submit([files])
    └── LocalBackend.submit()
            └── asyncio.create_task(_run_one()) × N files
                    └── asyncio.Semaphore(concurrency)
                            └── pipeline.run(file) — parse → chunk → embed → index
```

- All tasks run in the same Python process and event loop
- `concurrency` controls how many files run in parallel
- Completed results are stored in an in-memory `_BatchState` dict
- Batch state is **lost** if the API process restarts

---

## Starting the stack

```bash
# Minimal — just OpenSearch + API
docker compose up opensearch openrag-backend

# Or run the API locally (against a running OpenSearch)
PIPELINE_EXECUTION_BACKEND=local \
OPENSEARCH_HOST=localhost \
uv run uvicorn api.main:app --reload --port 8000
```

---

## Testing

### Submit a file

```bash
curl -X POST http://localhost:8000/api/v1/pipeline/upload \
  -F "files=@/path/to/document.pdf"
# Response: {"batch_id": "abc-123"}
```

### Poll progress

```bash
curl http://localhost:8000/api/v1/pipeline/status/abc-123 | jq
# {
#   "total": 1,
#   "completed": 1,
#   "failed": 0,
#   "in_flight": [],
#   "results": [{"status": "success", "chunks_indexed": 42, ...}]
# }
```

### Test concurrency

```bash
# Submit 10 files at once — only `concurrency` run in parallel
for i in $(seq 1 10); do
  cp /path/to/document.pdf /tmp/doc_${i}.pdf
done

curl -X POST http://localhost:8000/api/v1/pipeline/upload \
  $(for i in $(seq 1 10); do echo "-F files=@/tmp/doc_${i}.pdf"; done)
```

### Confirm no retry on failure

```bash
# Stop OpenSearch mid-batch to observe failure behaviour
docker stop os

# Submit a file
curl -X POST http://localhost:8000/api/v1/pipeline/upload \
  -F "files=@/path/to/document.pdf"

# Check status — will show failed, no retry
curl http://localhost:8000/api/v1/pipeline/status/<batch_id> | jq .failed
# → 1 (permanent failure, no retry in local mode)

# Restart OpenSearch
docker start os
# Re-submit manually to recover
```

---

## Failure behaviour

| Scenario | Outcome in local mode |
|---|---|
| Network timeout (OpenAI, OpenSearch) | `status="failed"`, logged, no retry |
| Corrupt / unreadable file | `status="failed"`, logged |
| No chunks produced | `status="skipped"`, logged |
| Exception during parse | `status="failed"`, `error` field populated |
| API process restart | All in-flight tasks lost; batch state gone |

For retry and DLQ support, switch to `redis` mode.

---

## Limits

- **Single node only** — no horizontal scaling across multiple API pods
- **No persistence** — batch state is lost on process restart
- **No retry** — failures are terminal
- **Memory accumulation** — long-running API processes accumulate Python heap
  from completed pipeline runs; restart periodically or use `redis` mode for
  workloads that run continuously

---

## Switching to redis mode

```bash
# Add Redis (one command), switch backend
docker run -d -p 6379:6379 redis:7-alpine
export PIPELINE_EXECUTION_BACKEND=redis
export REDIS_HOST=localhost
```

No other code changes needed — the `ExecutionBackend` protocol is the same
interface.
