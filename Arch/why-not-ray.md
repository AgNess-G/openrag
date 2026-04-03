# Why Ray Was Not Opted For

Ray was the execution backend in Generation 2 of the composable pipeline.
It has been fully removed in Generation 3 and replaced with a Redis queue
+ KEDA ScaledJob approach. This document records the reasoning so the
decision is explicit and revisitable.

---

## 1. What Ray Does Well

Ray is a genuine distributed computing framework. It excels at:

- **GPU-aware scheduling** — place compute-intensive tasks on GPU nodes natively
- **Object store** — pass large numpy arrays between tasks without serialisation overhead
- **Stage-level parallelism** — embed 500 chunks across 4 GPUs as nested Ray tasks
- **Zero infra for local dev** — `ray.init()` on a laptop with no external services
- **Lineage-based fault recovery** — replay failed tasks from their inputs

For ML training, simulation, or GPU-heavy inference pipelines, Ray is the right
tool. For OpenRAG's use case it turned out to be the wrong abstraction.

---

## 2. The Problem: Always-On Head Node

Ray requires a **head node** — a coordinator process that manages the Global
Control Store (GCS), the object store, and task scheduling. The head node must
be running before any work can be submitted.

In Docker Compose this means a `ray-head` container. On Kubernetes this means
a KubeRay `RayCluster` head pod. Neither can scale to zero:

```
Ray cluster idle state (no files queued):
  ray-head:    2 CPU / 4 GB  ← always running  ← $$$ / month
  ray-worker:  2 CPU / 4 GB  × N               ← can scale to 0
```

A typical `ray-head` on IKS costs ~$100–200/month even when no documents are
being ingested. This is the dominant cost at low utilisation — exactly the
scenario OpenRAG faces outside business hours or between ingestion bursts.

---

## 3. The Problem: Memory Not Released

Ray reuses worker processes across tasks for performance (avoiding Python
startup overhead). A worker that processed a 100 MB PDF retains that memory
until the worker is explicitly killed or the cluster is restarted.

The consequence: **nodes do not scale down**. The Kubernetes cluster autoscaler
will not remove a node that hosts a Ray worker pod with non-trivial memory
usage, even if the worker is idle. This breaks cost optimisation at the
infrastructure level — the cluster autoscaler has no way to recover idle memory
from long-lived Ray workers.

```
Ray worker after processing (idle):
  process memory: 512 MB–2 GB (Python heap, cached model weights, aiohttp pool)
  K8s node autoscaler: cannot evict non-zero memory pod safely
  node: stuck at minimum size
```

---

## 4. The Problem: Operational Complexity

Running KubeRay in production requires:

1. **KubeRay operator** — custom CRD installation and lifecycle management
2. **RayCluster manifest** — head/worker resource specs, port exposure
3. **Helm chart overrides** — wiring `RAY_ADDRESS` into the API deployment
4. **Ray Dashboard** — separate port (`:8265`), separate auth considerations
5. **Worker image** — same image as API but launched with `ray start --address`
6. **Version alignment** — Ray version must match between head, workers, and the `ray` pip package

This is significant ops overhead for a system whose primary job is document
ingestion. The Ray cluster became the most complex component to operate,
upgrade, and debug.

---

## 5. The Problem: Dependency Weight

The `ray[default]` package is ~300 MB installed. It includes:

- Ray core (C++/Python distributed runtime)
- gRPC, protobuf, aiohttp
- Dashboard dependencies (aioredis, aiofiles, opencensus)
- pyarrow (for the object store)

This bloats the container image, slows CI builds, and increases the attack
surface. The `redis` package (the replacement) is ~2 MB.

---

## 6. The Problem: No True Scale-to-Zero

Ray's `address: auto` mode on a single machine (local dev) works well. But in
Kubernetes, "scale to zero" means the head node must also stop — which Ray
does not support. KubeRay has a `suspend` feature but it requires explicit
orchestration and has seconds-to-minutes cold-start time.

KEDA ScaledJobs with Redis achieve genuine scale-to-zero: when the queue is
empty, there are **zero worker pods**. KEDA itself is a lightweight operator
that costs negligible resources.

---

## 7. What We Use Instead and Why

| Ray capability | How we replace it |
|---|---|
| Task queue | Redis LIST (`pipeline:queue`) — 2 MB dep, any K8s |
| Worker pool | KEDA ScaledJob — creates K8s Jobs from queue depth |
| Scale-to-zero | Native — no items → 0 Jobs |
| Memory release | K8s Job exits after completion — OS reclaims all memory |
| Fault tolerance | App-level retry (3×, exponential backoff) + DLQ in Redis |
| Batch state persistence | Redis HASH — survives API restart, shared across API replicas |
| Local dev (no K8s) | `mode: local` — asyncio workers in the API process, Redis in Docker |
| GPU scheduling | K8s node selectors / tolerations on the Job spec |
| Monitoring | Redis CLI, any Redis UI; KEDA metrics via Prometheus |

### What we lose

| Ray capability | Impact | Acceptable? |
|---|---|---|
| GPU-aware task placement | Must set node selectors manually on KEDA Job spec | Yes — one config line |
| Object store (zero-copy arrays) | Workers download from temp path or OpenSearch | Yes — files are small relative to ML training data |
| Stage-level parallelism | Each file is one Job; chunk embedding is sequential within the Job | Yes — embedding batch_size=200 is fast enough |
| Lineage-based replay | Re-queue from DLQ manually or via script | Yes — DLQ is explicit and inspectable |

---

## 8. Decision Summary

Ray is the right tool when you need:
- GPU cluster scheduling with compute-aware placement
- Stage-level distributed parallelism (scatter/gather across a cluster)
- Object store for passing large arrays between tasks

OpenRAG needs:
- **Scale to zero** — the dominant cost driver at low utilisation
- **Memory release** — required for cluster autoscaler to work
- **Simple ops** — one Redis service, one KEDA manifest, no custom CRDs
- **Low dependency weight** — fast builds, small images

The document ingestion pipeline is a bag-of-tasks workload: each file is
independent, stateless, and CPU-bound for seconds to minutes. This is exactly
the workload that a queue + ephemeral workers pattern handles optimally. Ray
adds distributed computing infrastructure that this workload does not need.

**Ray was not opted for because its cost model (always-on head, long-lived
workers) is the opposite of what a bursty, cost-sensitive ingestion service
requires.**
