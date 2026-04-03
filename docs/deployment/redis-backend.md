# Redis Execution Backend

The Redis backend replaces Ray as the execution engine for the composable
ingestion pipeline.  It uses a Redis list as a work queue and supports
two operating modes that share identical code and Redis schema:

| Mode | Who drains the queue | When to use |
|------|---------------------|-------------|
| `local` | Asyncio tasks inside the API process | Local dev, single-node deployments |
| `worker` | External K8s Jobs triggered by KEDA | Kubernetes / cloud production |

---

## Failure handling

Every file goes through a 3-tier failure model inside the worker:

```
pipeline.run(file)
    │
    ├─ status=="failed" AND attempt < max_retries
    │      → exponential backoff: base * 2^attempt  (capped at max)
    │      → re-enqueue with attempt+1
    │
    ├─ status=="failed" AND attempt >= max_retries
    │      → Dead Letter Queue  (pipeline:dlq:{batch_id})
    │      → surfaced in get_progress() as status="failed" with [DLQ] prefix
    │
    └─ status=="success" | "skipped"
           → write to results hash  (pipeline:results:{batch_id})
```

Default retry policy (configurable in YAML or env vars):

| Setting | Default | Env var |
|---------|---------|---------|
| `max_retries` | 3 | `REDIS_MAX_RETRIES` |
| `retry_backoff_base` | 1.0 s | — |
| `retry_backoff_max` | 60.0 s | — |

Backoff schedule: 1 s → 2 s → 4 s (capped at 60 s).

---

## Testing locally — Mode 1: `local` (no external workers)

The simplest path.  Redis runs in Docker; the API process itself spawns
asyncio workers that drain the queue.  This is identical to the
`LocalBackend` experience but with retry + DLQ on top.

### 1. Start Redis

```bash
docker run -d --name openrag-redis -p 6379:6379 redis:7-alpine \
  redis-server --maxmemory 256mb --maxmemory-policy allkeys-lru --save ""
```

Or with docker-compose:

```bash
docker compose --profile redis up redis
```

### 2. Run the API with the redis backend

```bash
PIPELINE_EXECUTION_BACKEND=redis \
REDIS_HOST=localhost \
REDIS_WORKER_MODE=local \
PIPELINE_CONFIG_FILE=src/pipeline/presets/composable-redis.yaml \
uv run uvicorn api.main:app --reload
```

### 3. Upload a file through the UI or API

```bash
curl -X POST http://localhost:8000/api/v1/pipeline/upload \
  -F "files=@/path/to/test.pdf"
# returns {"batch_id": "..."}
```

### 4. Poll progress

```bash
BATCH_ID="<paste batch_id>"
curl http://localhost:8000/api/v1/pipeline/status/$BATCH_ID | jq
```

### 5. Inspect Redis directly

```bash
# Queue depth (should drain to 0)
docker exec openrag-redis redis-cli LLEN pipeline:queue

# Results for the batch
docker exec openrag-redis redis-cli HGETALL pipeline:results:$BATCH_ID

# Dead letter queue (empty = no permanent failures)
docker exec openrag-redis redis-cli LRANGE pipeline:dlq:$BATCH_ID 0 -1

# In-flight set
docker exec openrag-redis redis-cli SMEMBERS pipeline:inflight:$BATCH_ID
```

### 6. Test retry behaviour

Force a failure to verify retries and DLQ:

```bash
# Stop OpenSearch to simulate a transient embedding/index failure
docker stop os

# Submit a file — it will fail, be retried 3× then go to DLQ
curl -X POST http://localhost:8000/api/v1/pipeline/upload \
  -F "files=@/path/to/test.pdf"

# Watch the retry counter increment in the queue item
docker exec openrag-redis redis-cli LRANGE pipeline:queue 0 -1

# Restart OpenSearch — next retry attempt succeeds
docker start os
```

### 7. Test cancellation

```bash
# Submit a large batch
BATCH_ID=$(curl -sX POST http://localhost:8000/api/v1/pipeline/upload \
  -F "files=@doc1.pdf" -F "files=@doc2.pdf" | jq -r .batch_id)

# Cancel it
curl -X DELETE http://localhost:8000/api/v1/pipeline/status/$BATCH_ID

# Verify cancelled flag
docker exec openrag-redis redis-cli GET pipeline:cancelled:$BATCH_ID
```

---

## Testing locally — Mode 2: `worker` (simulated KEDA)

This mode separates the API server from the workers exactly as KEDA does
in Kubernetes.  The API only enqueues; separate worker containers drain the
queue.  Use `--profile redis-worker` to start everything at once.

### 1. Start the full stack with workers

```bash
docker compose --profile redis-worker up --build
```

This starts:
- `openrag-backend` — API server with `REDIS_WORKER_MODE=worker`
- `redis` — Redis queue
- `pipeline-worker` (×2 replicas) — worker containers running `job_worker.py`
- `opensearch`

### 2. Verify the separation

```bash
# API enqueues but does NOT process
docker logs openrag-backend | grep "Redis backend: batch submitted"

# Workers process the items
docker logs openrag-pipeline-worker-1 | grep "Worker: processing"
docker logs openrag-pipeline-worker-2 | grep "Worker: processing"
```

### 3. Scale workers up/down manually

```bash
# Scale to 5 workers (simulates KEDA scaling up)
docker compose --profile redis-worker up --scale pipeline-worker=5 -d

# Scale to 0 (simulates KEDA scale-to-zero)
docker compose --profile redis-worker up --scale pipeline-worker=0 -d

# Queue depth should still be inspectable from Redis
docker exec openrag-redis redis-cli LLEN pipeline:queue
```

### 4. Verify memory is released on worker exit

```bash
# Start workers, submit a batch, wait for completion, then check workers stop
docker stats --no-stream | grep pipeline-worker

# After queue drains, workers exit and Docker removes the containers
# (KEDA would destroy K8s Jobs — same effect)
docker ps | grep pipeline-worker   # should show 0 containers
```

### 5. Test the single-worker path (closest to K8s Job)

```bash
# Run exactly one worker manually, just like a K8s Job would
docker compose --profile redis-worker run --rm pipeline-worker

# It processes everything in the queue, then exits with code 0
echo "Exit code: $?"
```

---

## Deploying to Kubernetes with KEDA

### Prerequisites

```bash
# Install KEDA
kubectl apply -f https://github.com/kedacore/keda/releases/download/v2.15.1/keda-2.15.1.yaml

# Create the secret with your credentials
kubectl create secret generic openrag-secrets \
  --from-literal=OPENSEARCH_HOST=<host> \
  --from-literal=OPENSEARCH_PASSWORD=<password> \
  --from-literal=OPENAI_API_KEY=<key>
```

### Deploy Redis + KEDA ScaledJob

```bash
kubectl apply -k kubernetes/redis/
```

### Update the API deployment to use worker mode

```bash
kubectl set env deployment/openrag-backend \
  PIPELINE_EXECUTION_BACKEND=redis \
  REDIS_HOST=openrag-redis \
  REDIS_WORKER_MODE=worker
```

### Verify KEDA is working

```bash
# Check ScaledJob
kubectl get scaledjob openrag-pipeline-worker

# Check Jobs created after ingestion
kubectl get jobs -l app=openrag-pipeline-worker -w

# Check queue depth via KEDA metrics
kubectl describe scaledjob openrag-pipeline-worker | grep -A5 "Triggers"

# Confirm scale-to-zero: queue empty → 0 Jobs
kubectl get jobs -l app=openrag-pipeline-worker
# Expected: No resources found
```

### Verify cost behaviour

```bash
# Check no idle worker pods when queue is empty
kubectl get pods -l app=openrag-pipeline-worker
# Expected: No resources found

# Inspect a completed Job's logs before it is garbage-collected
kubectl logs -l app=openrag-pipeline-worker --tail=50

# DLQ entries (permanent failures)
kubectl exec -it deployment/openrag-redis -- \
  redis-cli LRANGE pipeline:dlq:<batch_id> 0 -1
```

### Tune scaling parameters

Edit `kubernetes/redis/keda-scaledjob.yaml`:

```yaml
triggers:
  - type: redis
    metadata:
      listLength: "5"    # ↓ = more Jobs, faster processing; ↑ = fewer Jobs, cheaper
pollingInterval: 15      # ↓ = faster response to queue growth
maxReplicaCount: 50      # tune based on your node pool capacity
```

---

## Configuration reference

All settings can be overridden via environment variables without editing YAML.

| YAML path | Env var | Default | Description |
|-----------|---------|---------|-------------|
| `execution.backend` | `PIPELINE_EXECUTION_BACKEND` | `local` | Set to `redis` to enable |
| `execution.redis.host` | `REDIS_HOST` | `localhost` | Redis hostname |
| `execution.redis.port` | `REDIS_PORT` | `6379` | Redis port |
| `execution.redis.password` | `REDIS_PASSWORD` | — | Redis AUTH password |
| `execution.redis.mode` | `REDIS_WORKER_MODE` | `local` | `local` or `worker` |
| `execution.redis.max_retries` | `REDIS_MAX_RETRIES` | `3` | Per-file retry limit |
| `execution.redis.result_ttl` | — | `3600` | Seconds to keep results in Redis |
| `execution.concurrency` | `PIPELINE_EXECUTION_CONCURRENCY` | `4` | Workers in local mode |
