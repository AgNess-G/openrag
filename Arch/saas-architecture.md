# OpenRAG: SaaS Architecture — Benefits, Trade-offs, and Cost Strategy

## What this architecture is

OpenRAG's Gen 3 architecture is a **queue-driven, scale-to-zero pipeline** built on:

- **Stateless API** (FastAPI backend, N replicas, KEDA-scaled)
- **Redis queue** (IBM Databases for Redis or self-hosted)
- **Ephemeral workers** (K8s Jobs, 0→N, KEDA-triggered, exit when idle)
- **OpenSearch** (persistent, single StatefulSet or IBM managed)
- **Helm chart** (single source of truth for all K8s config)

The key design principle: **no component holds state except OpenSearch and Redis**. Everything else is replaceable, scalable, and disposable.

---

## Architecture diagram

```
                         ┌─────────────────────────────────────┐
                         │           IBM Cloud / K8s            │
                         │                                      │
  Users ──► Ingress ──►  │  Frontend (2-N pods, HPA)           │
                         │      │                               │
                         │      ▼                               │
                         │  Backend API (2-N pods)              │
                         │  KEDA: CPU + queue depth             │
                         │      │           │                   │
                         │      │     enqueue files             │
                         │      │           │                   │
                         │      ▼           ▼                   │
                         │  OpenSearch   Redis queue            │
                         │  (StatefulSet) (IBM Databases)       │
                         │                  │                   │
                         │            KEDA polls depth          │
                         │                  │                   │
                         │                  ▼                   │
                         │  pipeline-worker Jobs (0→20)         │
                         │  ┌──────┐┌──────┐┌──────┐           │
                         │  │ Job  ││ Job  ││ Job  │  ...       │
                         │  │parse ││parse ││parse │           │
                         │  │chunk ││chunk ││chunk │           │
                         │  │embed ││embed ││embed │           │
                         │  │index ││index ││index │           │
                         │  └──────┘└──────┘└──────┘           │
                         │  (exit when idle, node scales down)  │
                         └─────────────────────────────────────┘
```

---

## Pros

### 1. True scale-to-zero compute cost
Worker Jobs exit as soon as the queue is empty. Kubernetes node autoscaler then terminates the spot node. At zero ingestion activity, worker cost is **$0**.

Compare with always-on approaches:
| Approach | Idle cost/month |
|---|---|
| Ray head node (Gen 2) | ~$80–150 (m-series node) |
| Fixed worker pool (2 pods) | ~$30–60 |
| KEDA ScaledJob (Gen 3) | **$0** |

### 2. Unit economics scale linearly
Cost per document is predictable and constant regardless of volume:

```
Cost per doc ≈ (parse_seconds × cpu_price) + (embed_tokens × token_price)
```

At 1 doc/day or 10,000 docs/day, cost per doc stays the same. There is no "minimum floor" of always-on infra per tenant.

### 3. Multi-tenant ready
Each tenant's ingestion runs in isolated worker Jobs. One tenant uploading 1,000 PDFs doesn't starve another tenant's small upload — KEDA distributes Jobs across the pool. Queue keys can be namespaced per tenant (`pipeline:queue:{tenant_id}`) with no code change.

### 4. Burst handling without pre-provisioning
A customer that uploads nothing for 3 weeks then drops 500 documents gets 20 workers in ~30 seconds. No capacity planning needed. The spot node pool expands on demand and contracts to zero after.

### 5. Failure isolation
Each document runs in its own asyncio task within a Job. A PDF that causes an OOM doesn't affect other documents. A crashed Job is retried at the queue level (3-tier: retry → skip → DLQ). No single point of failure in the processing path.

### 6. Portable across clouds
The Helm chart + KEDA combination works identically on:
- IBM Cloud IKS
- AWS EKS
- GCP GKE
- Azure AKS
- On-prem K8s

Only `values-ibm.yaml` (storage class, image registry, load balancer annotations) changes between clouds. The application code and K8s manifests are identical.

### 7. Helm chart = operator-friendly lifecycle
```bash
# Deploy
helm install openrag ./charts/openrag -f values-ibm.yaml

# Upgrade with zero downtime (PDBs ensure min 1 pod stays alive)
helm upgrade openrag ./charts/openrag -f values-ibm.yaml --atomic

# Rollback
helm rollback openrag 1

# Diff before applying
helm diff upgrade openrag ./charts/openrag -f values-ibm.yaml
```

---

## Cons

### 1. Redis is a new operational dependency
In Gen 1/2, the only stateful component was OpenSearch. Gen 3 adds Redis. IBM Databases for Redis mitigates this (managed service, auto-failover, TLS) but adds ~$45–100/month and a new failure domain.

**Mitigation:** `local` execution mode (no Redis) for small deployments. Redis only needed at scale.

### 2. Cold start latency for workers
KEDA polling interval is 15 seconds. First-file-in-batch latency is:
```
upload → queue push → KEDA poll (up to 15s) → Job schedule → container pull → start
= ~30–60 seconds before first file starts processing
```

For interactive single-file uploads, the local backend mode is faster (zero cold start). Worker mode is optimised for batch throughput, not interactive latency.

**Mitigation:** Keep `minReplicaCount: 1` for workers during business hours (warm pool), scale to 0 overnight.

### 3. Short jobs are inefficient on K8s
A 2-second text file processed as a K8s Job has more overhead (Job scheduling, container start) than the processing itself. Worker Jobs are efficient for PDFs (10–120 seconds each) but wasteful for tiny text files.

**Mitigation:** `targetQueueLength: 5` — each Job drains 5 items minimum, amortising the startup cost. Alternatively, route small files to the local backend and large files to Redis workers.

### 4. KEDA adds cluster complexity
KEDA is a CRD-based operator. It must be installed, upgraded, and monitored. In clusters where KEDA is unavailable (some managed K8s with restricted CRD access), fallback to HPA is provided in the chart but loses queue-depth-driven scaling.

### 5. OpenSearch is not managed (by default)
The Helm chart deploys OpenSearch as a StatefulSet. This works but requires manual attention for:
- Index mapping changes
- Snapshot/restore for backup
- Memory/heap tuning as data grows

**Mitigation:** Use OpenSearch Operator or IBM OpenSearch managed service for production.

---

## Cost model for SaaS deployment

### Tier 1 — Small team / startup ($150–300/month)

```
IKS:  2× bx2.2x8 workers (backend + frontend + opensearch)  ~$120/month
Redis: IBM Databases standard 1GB                            ~$45/month
Spot pool: 0 nodes at rest, ~1–2 nodes during ingestion      ~$10/month
COS:  standard bucket (documents)                            ~$5/month
Total:                                                        ~$180/month
```

### Tier 2 — Growing SaaS (multi-tenant, $500–800/month)

```
IKS:  3× bx2.4x16 (HA backend, opensearch, system)          ~$360/month
Redis: IBM Databases standard 2GB                            ~$80/month
Spot pool: avg 2 nodes running 8hrs/day                      ~$80/month
COS:  smart tier (auto-archive old docs)                     ~$20/month
Registry: IBM CR                                             ~$5/month
Total:                                                        ~$545/month
```

### Tier 3 — Enterprise ($2,000–4,000/month)

```
IKS:  5× bx2.8x32 (HA everything, dedicated opensearch)     ~$1,800/month
Redis: IBM Databases enterprise (HA, 4GB)                   ~$200/month
Spot pool: avg 5 nodes, 12hrs/day                           ~$300/month
COS:  smart tier + replication                              ~$100/month
Observability: IBM Log Analysis + Monitoring                ~$200/month
Total:                                                       ~$2,600/month
```

### Cost levers to pull

| Lever | Saving | Trade-off |
|---|---|---|
| Spot/preemptible nodes for workers | 60–70% worker cost | Workers can be interrupted mid-job (retry handles this) |
| Scale worker pool to 0 overnight | 50% spot node cost | 30–60s cold start on first morning upload |
| `smart` storage class on COS | 20–40% storage cost | Infrequent access objects auto-archived |
| Single-zone cluster | ~30% network cost | No zone-failure HA |
| Share OpenSearch across tenants | Eliminate per-tenant OS cost | Index isolation via naming convention |

---

## Leveraging for cost-effective SaaS

### Pattern 1 — Shared infrastructure, isolated data

Run one OpenRAG cluster per region. Tenant isolation via:
- OpenSearch index prefix: `tenant_{id}_documents`
- Redis queue key: `pipeline:queue:{tenant_id}`
- K8s namespace per tenant (optional, for NetworkPolicy isolation)

All tenants share the backend, workers, OpenSearch cluster, and Redis. Infra cost is amortised across tenants. At 50 tenants on Tier 2, cost per tenant is ~$11/month.

### Pattern 2 — Metered billing alignment

Because worker cost = actual processing time, you can bill tenants per document or per GB ingested with near-zero margin:

```
Tenant bill = docs_ingested × $0.005 + storage_gb × $0.02 + queries × $0.001
```

This maps directly to your actual IBM Cloud costs. As volume grows, margin improves (OpenSearch and backend are fixed costs amortised over more tenants).

### Pattern 3 — Regional deployment

Deploy one Helm release per region (`helm install openrag-eu`, `helm install openrag-us`). Only `values-{region}.yaml` changes. Same chart, same image. Useful for data residency compliance (GDPR, etc).

### Pattern 4 — Tiered compute for worker nodes

Use different node flavors for different document types:
- CPU-optimised nodes for PDF parsing (Docling)
- Standard nodes for text/markdown (MarkItDown)

Route via KEDA ScaledJob `nodeSelector` per pipeline preset. CPU-heavy jobs pay for CPU nodes only while running; other jobs use cheaper standard nodes.

### Pattern 5 — Warm pool during business hours only

```yaml
# In KEDA ScaledJob spec, add a time-based trigger alongside the queue trigger:
triggers:
  - type: redis
    ...
  - type: cron
    metadata:
      timezone: America/New_York
      start: "0 8 * * 1-5"    # warm up at 8am weekdays
      end:   "0 18 * * 1-5"   # scale down at 6pm
      desiredReplicas: "1"     # keep 1 warm worker during business hours
```

Eliminates cold start for interactive use during business hours. Scales to 0 outside hours.

---

## Summary

| Dimension | This Architecture |
|---|---|
| Idle cost | Near zero (scale to zero workers) |
| Burst handling | Automatic (KEDA 0→N in ~30s) |
| Failure isolation | Per-document (Job-level) |
| Cloud portability | High (Helm + KEDA, any K8s) |
| Operational complexity | Medium (KEDA, Redis, Helm) |
| Multi-tenancy | Native (queue key + index prefix) |
| Billing alignment | High (cost ∝ actual usage) |
| Cold start latency | 30–60s (mitigated by warm pool) |

The architecture is well-suited for **bursty, batch-heavy SaaS workloads** where ingestion happens in spikes (connector syncs, bulk uploads) rather than a steady stream. The unit economics improve with tenant count because fixed costs (backend, OpenSearch) are shared while variable costs (workers) scale exactly with usage.
