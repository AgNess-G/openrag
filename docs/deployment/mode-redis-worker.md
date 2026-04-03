# Execution Mode: `redis` / `mode: worker`

The API server only enqueues work items into Redis. Separate worker
processes — Docker Compose containers locally, or KEDA-triggered K8s Jobs
in the cloud — drain the queue. Workers exit after their slice is done,
fully releasing memory.

This is the **production mode** for Kubernetes deployments. It is also the
recommended mode for testing cloud behaviour locally.

---

## When to use

| Situation | Recommendation |
|---|---|
| Kubernetes production | ✅ Primary mode |
| Local simulation of K8s workers | ✅ `--profile redis-worker` |
| High document volume (100k+/day) | ✅ |
| Need true scale-to-zero | ✅ |
| Memory must be released between files | ✅ |
| Single developer machine, small batches | ❌ Use `redis/local` mode |

---

## How it differs from `redis/local` mode

| Concern | `redis` / `mode: local` | `redis` / `mode: worker` |
|---|---|---|
| Who runs the pipeline | API process (asyncio tasks) | Separate worker containers / K8s Jobs |
| Memory release | On queue empty (workers exit) | On every file (Job exits) |
| Scale-to-zero | Partial (workers stop, API stays) | Full (0 Jobs when queue empty) |
| Crash recovery | Queue items orphaned | K8s Job restarts (backoffLimit) |
| Horizontal API scaling | Yes (shared Redis) | Yes (shared Redis) |
| Local test infra | Redis only | Redis + worker containers |

---

## Architecture

```
API process (mode=worker)
  └── RedisBackend.submit()
        └── RPUSH pipeline:queue × N   ← only thing the API does
        └── return batch_id            ← immediately, no workers spawned

Separately (Docker Compose / KEDA K8s Job):
  pipeline-worker container / Job
    └── job_worker.py main()
          ├── loads PipelineConfig from env
          ├── builds IngestionPipeline
          └── loop:
                ├── BLPOP pipeline:queue (15s timeout)
                ├── _process_item()
                │     ├── pipeline.run(file)
                │     ├── retry logic (3× backoff)
                │     └── write result or DLQ
                └── exit when queue empty (idle timeout)
```

---

## Local testing with docker-compose

### Start the full stack

```bash
# Starts: openrag-backend (mode=worker), redis, pipeline-worker ×2, opensearch
docker compose --profile redis-worker up --build
```

### Scale workers

```bash
# 5 workers (simulates KEDA scaling up)
docker compose --profile redis-worker up --scale pipeline-worker=5 -d

# 0 workers (simulates KEDA scale-to-zero)
docker compose --profile redis-worker up --scale pipeline-worker=0 -d
```

### Verify separation: API enqueues, workers process

```bash
# Terminal 1 — watch API logs (should see "batch submitted", nothing else)
docker logs -f openrag-backend | grep -E "submitted|backend"

# Terminal 2 — watch worker logs (should see "processing", "file done")
docker logs -f $(docker ps -q -f name=pipeline-worker) | grep -E "processing|done|failed|DLQ"

# Terminal 3 — watch queue depth
watch -n1 'docker exec openrag-redis redis-cli LLEN pipeline:queue'
```

### Submit files

```bash
BATCH=$(curl -sX POST http://localhost:8000/api/v1/pipeline/upload \
  -F "files=@/path/to/document.pdf" | jq -r .batch_id)
echo "Batch: $BATCH"

# Poll progress (reads from Redis, not API memory)
curl http://localhost:8000/api/v1/pipeline/status/$BATCH | jq
```

### Test memory release

```bash
# After workers drain the queue, they exit
docker ps | grep pipeline-worker
# → no running workers

# Check memory is actually released
docker stats --no-stream | grep pipeline-worker
# → no rows (containers gone)

# K8s equivalent: kubectl get pods -l app=openrag-pipeline-worker
# → No resources found
```

### Test single-worker path (closest to K8s Job)

```bash
# Run exactly one worker manually — like a K8s Job
docker compose --profile redis-worker run --rm --no-deps pipeline-worker

# It processes everything, logs "queue empty, exiting", exits 0
echo "Exit: $?"
```

### Test crash recovery (spot node eviction simulation)

```bash
# Submit a batch
BATCH=$(curl -sX POST http://localhost:8000/api/v1/pipeline/upload \
  -F "files=@doc1.pdf" -F "files=@doc2.pdf" | jq -r .batch_id)

# Kill a worker mid-processing
docker kill $(docker ps -q -f name=pipeline-worker | head -1)

# The item was already BLPOP'd — it is gone from the queue
# In K8s: Job backoffLimit=0 → KEDA creates a new Job for remaining items
# Locally: start a fresh worker
docker compose --profile redis-worker up --scale pipeline-worker=2 -d

# Check results — some may have completed, some may be in DLQ
curl http://localhost:8000/api/v1/pipeline/status/$BATCH | jq
```

---

## Kubernetes deployment

### Prerequisites

```bash
# Install KEDA (one-time cluster setup)
kubectl apply -f \
  https://github.com/kedacore/keda/releases/download/v2.15.1/keda-2.15.1.yaml

# Create secret with credentials
kubectl create secret generic openrag-secrets \
  --from-literal=OPENSEARCH_HOST=<host> \
  --from-literal=OPENSEARCH_PASSWORD=<password> \
  --from-literal=OPENAI_API_KEY=<key>
```

### Deploy Redis + KEDA ScaledJob

```bash
kubectl apply -k kubernetes/redis/
```

### Switch the API to worker mode

```bash
kubectl set env deployment/openrag-backend \
  PIPELINE_EXECUTION_BACKEND=redis \
  REDIS_HOST=openrag-redis \
  REDIS_WORKER_MODE=worker
```

### Verify KEDA scaling

```bash
# Check ScaledJob status
kubectl get scaledjob openrag-pipeline-worker
kubectl describe scaledjob openrag-pipeline-worker | grep -A5 "Triggers"

# Watch Jobs appear when files are submitted
kubectl get jobs -l app=openrag-pipeline-worker -w

# Submit a file from the UI or API
# Jobs should appear within ~15 s (pollingInterval)

# After processing completes, Jobs should be cleaned up
kubectl get jobs -l app=openrag-pipeline-worker
# → only last 3 successful + 5 failed kept (historyLimit)
```

### Verify scale-to-zero

```bash
# Wait for queue to drain
kubectl exec -it deployment/openrag-redis -- redis-cli LLEN pipeline:queue
# → 0

# Check no worker pods
kubectl get pods -l app=openrag-pipeline-worker
# → No resources found

# Node autoscaler should now be free to remove spot nodes
kubectl get nodes
# → pool should scale down after cooldown
```

### Inspect results and DLQ

```bash
BATCH="<paste batch_id>"

kubectl exec deployment/openrag-redis -- \
  redis-cli HGETALL pipeline:results:$BATCH

kubectl exec deployment/openrag-redis -- \
  redis-cli LRANGE pipeline:dlq:$BATCH 0 -1
```

### Scale parameters

```bash
# Edit kubernetes/redis/keda-scaledjob.yaml then re-apply
kubectl apply -k kubernetes/redis/

# Key settings:
#   listLength: "5"     → 1 Job per 5 items  (lower = more Jobs)
#   maxReplicaCount: 50 → ceiling
#   pollingInterval: 15 → seconds between queue checks
```

---

## Cost model

```
Idle (queue empty):
  openrag-backend:  0.1 CPU / 256 MB    ~$5–10/mo
  openrag-redis:    50 m CPU / 128 MB   ~$5–15/mo managed
  pipeline-workers: 0                    $0
  Total:            ~$10–25/mo

Active (processing):
  1 Job = 1 CPU / 2 GB spot             ~$0.02–0.05/vCPU-hr
  ~2–5 CPU-sec/document
  → ~$0.00004–0.0001 per document
```

---

## Failure behaviour

| Scenario | Outcome |
|---|---|
| Network timeout (transient) | Retry up to `max_retries` with exponential backoff |
| Corrupt file (permanent) | Retry exhausted → `pipeline:dlq:{batch_id}` |
| Job OOM killed | Item lost (was already BLPOP'd); K8s backoffLimit re-creates Job for remaining items |
| Spot node eviction | Same as OOM kill |
| Redis unavailable | Worker exits with error; KEDA creates new Job when Redis recovers |
| All retries exhausted | DLQ entry; `get_progress()` surfaces as `status="failed"` with `[DLQ]` prefix |

---

## Job worker environment variables

| Variable | Default | Purpose |
|---|---|---|
| `REDIS_HOST` | `localhost` | Redis hostname |
| `REDIS_PORT` | `6379` | Redis port |
| `REDIS_PASSWORD` | — | Redis AUTH |
| `REDIS_WORKER_MODE` | `local` | Must be `worker` for external workers |
| `WORKER_IDLE_TIMEOUT` | `15` | Seconds to wait on empty queue before exiting |
| `PIPELINE_CONFIG_FILE` | built-in preset | Config YAML path |
| `PIPELINE_EXECUTION_BACKEND` | — | Set to `redis` |
| `OPENAI_API_KEY` | — | Embedder credential |
| `OPENSEARCH_HOST` | — | Index target |
| `OPENSEARCH_PASSWORD` | — | Index auth |
