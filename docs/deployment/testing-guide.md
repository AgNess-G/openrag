# Testing Guide: Local and Cloud (K8s) Setup

## Overview

There are three execution modes, each with a different testing approach:

| Mode | Backend | Workers | When to use |
|---|---|---|---|
| Local | `asyncio` in-process | None | Dev, quick iteration |
| Redis local | Redis queue | Podman containers (simulated KEDA) | Validate Redis/retry logic |
| Redis worker (K8s) | Redis queue | KEDA-spawned K8s Jobs | Full production fidelity |

---

## Prerequisites

```bash
# Install tools
brew install kind kubectl podman

# Build the backend image
make build-be

# Ensure .env exists with at minimum:
# OPENSEARCH_PASSWORD=...
# OPENAI_API_KEY=...
# PIPELINE_INGESTION_MODE=composable
```

---

## Option A — Local backend (no Redis, no K8s)

Simplest setup. Pipeline runs in-process using asyncio workers.

**.env settings:**
```
PIPELINE_EXECUTION_BACKEND=local
PIPELINE_INGESTION_MODE=composable
PIPELINE_CONFIG_FILE=src/pipeline/presets/composable-basic.yaml
```

**Run:**
```bash
podman compose --env-file .env up -d
```

**Access UI:** http://localhost:3000

**What runs in Podman:**
- `openrag-frontend` (port 3000)
- `openrag-backend` (port 8000)
- `opensearch` (port 9200)

**Test ingestion:**
1. Open http://localhost:3000 and complete onboarding
2. Upload a PDF or text file via the UI
3. Watch backend logs:
   ```bash
   podman logs -f openrag-backend
   ```
4. Expect to see: `parse → preprocess → chunk → embed → index` stages

**Test failure handling:**
```bash
# Disconnect network mid-ingest to force a retry
podman network disconnect openrag_default openrag-backend
# Reconnect after a few seconds
podman network connect openrag_default openrag-backend
```

---

## Option B — Redis local mode (simulated KEDA workers)

Redis queue with worker containers running in Podman. This is the recommended way to validate Redis/retry/DLQ logic before going to K8s.

**.env settings:**
```
PIPELINE_EXECUTION_BACKEND=redis
REDIS_HOST=redis
REDIS_WORKER_MODE=local
PIPELINE_EXECUTION_CONCURRENCY=4
REDIS_MAX_RETRIES=3
PIPELINE_CONFIG_FILE=src/pipeline/presets/composable-redis.yaml
```

**Run:**
```bash
# Start Redis + backend + frontend
podman compose --env-file .env --profile redis up -d

# Or with simulated KEDA workers (separate worker containers)
podman compose --env-file .env --profile redis-worker up -d
```

**Access UI:** http://localhost:3000

**What runs in Podman:**
- `openrag-frontend` (port 3000)
- `openrag-backend` (port 8000)
- `opensearch` (port 9200)
- `openrag-redis` (port 6379)
- `pipeline-worker` × 2 (when using `redis-worker` profile)

**Watch queue depth:**
```bash
podman exec openrag-redis redis-cli LLEN pipeline:queue
```

**Test horizontal scaling:**
```bash
# Scale workers up to simulate more KEDA Jobs
podman compose --env-file .env --profile redis-worker scale pipeline-worker=5

# Scale back down
podman compose --env-file .env --profile redis-worker scale pipeline-worker=1
```

**Test retry logic:**
```bash
# Watch DLQ after forcing failures
podman exec openrag-redis redis-cli KEYS "pipeline:dlq:*"
podman exec openrag-redis redis-cli LRANGE pipeline:dlq:<batch_id> 0 -1
```

**Test cancellation:**
```bash
# Submit a large batch via the UI, then cancel via API
curl -X POST http://localhost:8000/pipeline/cancel/<batch_id>

# Verify cancel flag was set in Redis
podman exec openrag-redis redis-cli EXISTS pipeline:cancelled:<batch_id>
```

**Test worker restart survival:**
```bash
# Kill a worker mid-processing
podman compose --env-file .env --profile redis-worker restart pipeline-worker

# Items should be re-queued and processed by surviving workers
podman exec openrag-redis redis-cli LLEN pipeline:queue
```

---

## Option C — Full K8s with kind + KEDA

Full production fidelity. KEDA spawns real K8s Jobs when the Redis queue fills.

### 1. Create kind cluster

```bash
kind create cluster --name openrag
```

### 2. Install KEDA

```bash
kubectl apply --server-side --force-conflicts \
  -f https://github.com/kedacore/keda/releases/download/v2.15.1/keda-2.15.1.yaml

# Wait for KEDA to be ready
kubectl wait --for=condition=ready pod -l app=keda-operator -n keda --timeout=120s
```

### 3. Load backend image into kind

```bash
# Export from Podman and load into kind
podman save langflowai/openrag-backend:latest -o /tmp/openrag-backend.tar
kind load image-archive /tmp/openrag-backend.tar --name openrag

# Verify image is present
docker exec openrag-control-plane crictl images | grep openrag-backend
```

### 4. Find host IP reachable from kind pods

kind pods need to reach OpenSearch and Redis running in Podman on your Mac.

```bash
# Get the gateway IP of the kind network (this is your Mac's IP from inside kind)
podman network inspect kind | python3 -c "
import sys, json
d = json.load(sys.stdin)
[print(s['gateway']) for n in d for s in n.get('subnets', []) if '.' in s.get('gateway','')]
"
# Typically: 10.89.1.1
```

Verify connectivity from inside kind:
```bash
kubectl run test-conn --rm -it --image=curlimages/curl -- \
  curl -sk -u admin:'<OPENSEARCH_PASSWORD>' \
  https://10.89.1.1:9200/_cluster/health
# Expect: {"status":"green"} or {"status":"yellow"}
```

### 5. Create K8s secret

Replace `10.89.1.1` with the gateway IP from step 4.

```bash
kubectl create secret generic openrag-secrets \
  --from-literal=OPENSEARCH_HOST=10.89.1.1 \
  --from-literal=OPENSEARCH_PORT=9200 \
  --from-literal=OPENSEARCH_USERNAME=admin \
  --from-literal=OPENSEARCH_PASSWORD='<your-opensearch-password>' \
  --from-literal=OPENAI_API_KEY='<your-openai-key>' \
  --from-literal=WATSONX_API_KEY='' \
  --from-literal=WATSONX_PROJECT_ID='' \
  --from-literal=WATSONX_ENDPOINT=''
```

### 6. Deploy Redis + KEDA ScaledJob

```bash
kubectl apply -k kubernetes/redis/
```

Verify:
```bash
kubectl get scaledjob openrag-pipeline-worker
kubectl get deployment openrag-redis
kubectl get svc openrag-redis
```

### 7. Point backend at in-cluster Redis

The backend (in Podman) needs to enqueue to the Redis running inside kind.
Port-forward the in-cluster Redis to localhost:

```bash
kubectl port-forward svc/openrag-redis 6380:6379 &
```

Update `.env`:
```
REDIS_HOST=localhost
REDIS_PORT=6380
REDIS_WORKER_MODE=worker   # backend enqueues only, K8s Jobs drain
PIPELINE_EXECUTION_BACKEND=redis
```

Restart backend:
```bash
podman compose --env-file .env up -d openrag-backend
```

### 8. Watch KEDA scale Jobs

Upload files via the UI (http://localhost:3000) and watch Jobs spawn:

```bash
# Watch Jobs being created
kubectl get jobs -w

# Watch pods
kubectl get pods -l app=openrag-pipeline-worker -w

# Check ScaledJob status
kubectl describe scaledjob openrag-pipeline-worker

# Queue depth (in-cluster Redis)
kubectl exec -it deploy/openrag-redis -- redis-cli LLEN pipeline:queue
```

### 9. Inspect worker logs

```bash
# Get a worker pod name
kubectl get pods -l app=openrag-pipeline-worker

# Tail logs
kubectl logs -f <pod-name>
```

### Teardown

```bash
# Remove kind cluster
kind delete cluster --name openrag

# Stop Podman stack
podman compose --env-file .env down
```

---

## Networking summary

```
Mac host
├── Podman network (openrag_default)
│   ├── openrag-backend   :8000
│   ├── openrag-frontend  :3000
│   ├── opensearch        :9200
│   └── openrag-redis     :6379
│
└── kind network (10.89.1.x)
    ├── keda-operator        (keda namespace)
    ├── openrag-redis        ClusterIP → :6379
    └── pipeline-worker Jobs (spawned by KEDA)
         └── connects to OpenSearch via 10.89.1.1:9200 (host gateway)
```

Kind pods reach Podman services via the kind network gateway (`10.89.1.1`), which is the Mac host. Podman services are port-mapped to the host, so they're reachable at that IP.
