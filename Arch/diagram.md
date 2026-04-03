# OpenRAG Ingestion Architecture — Evolution Diagram

Three generations of the ingestion architecture, from the original dual-path
system through the composable Ray-based pipeline, to the current
Redis/KEDA queue-driven design.

---

## 1. Generation 1 — Original Dual-Path Architecture

The baseline before the composable pipeline. Two hardcoded paths, no pluggable
stages, all in-process.

```mermaid
flowchart TB
    Client(["Client\nFile Upload"])

    subgraph api [API Layer]
        Upload["POST /ingest"]
        Switch{"DISABLE_INGEST\n_WITH_LANGFLOW?"}
    end

    subgraph langflow_path [Langflow Path — Default]
        direction TB
        LF["Langflow Container\n(separate service)"]
        LFDocling["Docling inside Langflow"]
        LFChunk["CharacterTextSplitter\n(hardcoded)"]
        LFEmbed["OpenAI Embedder\n(hardcoded)"]
        LFOS["OpenSearch\nper-chunk index"]
        LF --> LFDocling --> LFChunk --> LFEmbed --> LFOS
    end

    subgraph traditional_path [Traditional Path]
        direction TB
        TDocling["docling-serve / text\nprocess_text_file"]
        TChunk["page + table chunking\nextract_relevant"]
        TEmbed["Batched Embeddings\n(hardcoded provider)"]
        TOS["OpenSearch\nper-chunk index"]
        TDocling --> TChunk --> TEmbed --> TOS
    end

    subgraph workers [Concurrency]
        Sem["asyncio.Semaphore\nMAX_WORKERS in-process\nstate lost on restart"]
    end

    Client --> Upload --> Switch
    Switch -->|"false (default)"| Sem
    Switch -->|"true"| Sem
    Sem -->|"langflow"| LF
    Sem -->|"traditional"| TDocling
```

**Limitations:**
- Hardcoded stages — no way to swap parser, chunker, or embedder without code changes
- In-process `asyncio.Semaphore` — tasks lost on restart, no visibility
- Per-chunk OpenSearch writes — no bulk API, high latency at scale
- Two parallel codepaths to maintain

---

## 2. Generation 2 — Composable Pipeline with Ray *(superseded)*

Protocol-based pluggable pipeline with two execution backends: local asyncio and
Ray for distributed processing.

> **Note:** Ray has been removed in Generation 3. This section documents the
> intermediate state for historical reference. See `Arch/why-not-ray.md` for
> the full reasoning.

```mermaid
flowchart TB
    Client(["Client\nFile Upload"])

    subgraph api [API Layer]
        Upload["POST /ingest"]
        Switch{"ingestion_mode?"}
    end

    subgraph backend_choice [Execution Backend]
        BackendSwitch{"execution.backend?"}
    end

    subgraph local_backend [local — Default · Zero Infra]
        LocalSem["asyncio.Semaphore\nexecution.concurrency\nin-process"]
    end

    subgraph ray_backend [ray — Scalable · Distributed ⚠ removed]
        RayCluster["Ray Cluster\nHead + Workers\nAlways-on head node cost"]
    end

    subgraph pipeline [Composable Pipeline]
        direction LR
        Parser2["Parser"]
        Chunker2["Chunker"]
        Embedder2["Embedder"]
        Indexer2["Indexer"]
        Parser2 --> Chunker2 --> Embedder2 --> Indexer2
    end

    Client --> Upload --> Switch
    Switch -->|"composable"| BackendSwitch
    BackendSwitch -->|"local"| LocalSem --> pipeline
    BackendSwitch -->|"ray ⚠"| RayCluster --> pipeline
```

**Why Gen 2 was improved:**
- Ray head node always running — fixed monthly cost even at zero load
- Memory not released between tasks in long-lived Ray workers
- KubeRay cluster adds operational complexity (head CRD, worker auto-scaler)
- Ray dependency (~300 MB) bloats the container image

---

## 3. Generation 3 — Redis Queue + KEDA *(current)*

Stateless, ephemeral workers triggered by queue depth. True scale-to-zero.
Same pipeline code; new execution layer below it.

```mermaid
flowchart TB
    Client(["Client\nFile Upload"])

    subgraph api [API Tier — always-on, minimal]
        Upload["POST /ingest"]
        Switch{"ingestion_mode?"}
        PipelineSvc["PipelineService\nRedisBackend"]
    end

    subgraph queue [Redis Queue — 128–512 MB fixed]
        Q[("pipeline:queue\nLIST")]
        Results[("pipeline:results:{id}\npipeline:dlq:{id}\nHASH / LIST")]
    end

    subgraph scaler [KEDA ScaledJob]
        KEDA["Polls queue every 15 s\n0 → 50 Jobs based on depth\nScale-to-zero when empty"]
    end

    subgraph workers [K8s Jobs — ephemeral]
        W1["Job 1\n1 CPU / 2 GB\nexits when done\nmemory released"]
        W2["Job 2\n1 CPU / 2 GB\nexits when done\nmemory released"]
        WN["Job N\n1 CPU / 2 GB\nexits when done\nmemory released"]
    end

    subgraph pipeline [Composable Pipeline — per Job]
        direction LR
        Parser3["Parser\nauto | docling\nmarkitdown | text"]
        Pre3["Preprocessors\ncleaning | dedup"]
        Chunker3["Chunker\nrecursive | semantic\ncharacter | docling_hybrid"]
        Embedder3["Embedder\nopenai | watsonx\nollama | huggingface"]
        Indexer3["Indexer\nopensearch_bulk"]
        Parser3 --> Pre3 --> Chunker3 --> Embedder3 --> Indexer3
    end

    subgraph storage [Storage]
        OS[("OpenSearch\nVector Index")]
    end

    Client --> Upload --> Switch
    Switch -->|"composable"| PipelineSvc
    PipelineSvc -->|"RPUSH"| Q
    Q -->|"queue depth"| KEDA
    KEDA -->|"creates"| W1 & W2 & WN
    W1 & W2 & WN -->|"BLPOP"| Q
    W1 & W2 & WN --> pipeline
    pipeline --> OS
    W1 & W2 & WN -->|"HSET result / DLQ"| Results
```

**Also supported — local mode (no K8s needed):**

```mermaid
flowchart LR
    API["FastAPI\nPipelineService\nRedisBackend mode=local"]
    Redis[("Redis\nlocalhost:6379")]
    Workers["asyncio Tasks\nN concurrent\nsame process"]
    Pipeline["Composable Pipeline"]

    API -->|"RPUSH"| Redis
    API -->|"spawns"| Workers
    Workers -->|"BLPOP"| Redis
    Workers --> Pipeline
```

---

## 4. Comparison — All Three Generations

| Concern | Gen 1 | Gen 2 (Ray) | Gen 3 (Redis/KEDA) |
|---|---|---|---|
| Stages | Hardcoded | Pluggable YAML | Pluggable YAML |
| Idle cost | ~$0 | $$$ (Ray head always on) | $ (Redis only) |
| Scale to zero | N/A | No | Yes |
| Memory release | On restart | Partial (long-lived workers) | Yes (Job exits) |
| Fault tolerance | None | Ray retries | App retries + DLQ |
| Batch state | In-memory | In-memory | Redis (survives restart) |
| Local dev infra | None | None (`local` backend) | Redis Docker only |
| Cloud infra | N/A | KubeRay cluster | KEDA + Redis |
| Dependency size | N/A | +300 MB (Ray) | +2 MB (`redis`) |
| Horizontal API scale | No | No (shared Ray refs) | Yes (shared Redis queue) |
| GPU scheduling | No | Yes (Ray native) | Via node selectors |

---

## 5. Deployment Topology — Gen 3

```mermaid
flowchart TB
    subgraph local_dev [Local Dev — mode: local]
        DevAPI["openrag-backend\n+ asyncio workers inline"]
        DevRedis["Redis\ndocker run redis:7-alpine"]
        DevAPI <-->|"queue"| DevRedis
    end

    subgraph docker_workers [Docker Compose — profile: redis-worker]
        DocAPI["openrag-backend\nmode: worker\nenqueue only"]
        DocRedis["redis service"]
        DocW1["pipeline-worker ×1"]
        DocW2["pipeline-worker ×2"]
        DocWN["pipeline-worker ×N"]
        DocAPI -->|"RPUSH"| DocRedis
        DocW1 & DocW2 & DocWN -->|"BLPOP"| DocRedis
    end

    subgraph kubernetes [Kubernetes — KEDA ScaledJob]
        K8sAPI["openrag-backend\nDeployment\nmode: worker"]
        K8sRedis["Redis\nClusterIP Service"]
        K8sKEDA["KEDA ScaledJob\n0 → 50 Jobs\npolling: 15 s"]
        K8sJobs["K8s Jobs\nspot node pool\nephemeral"]
        K8sAPI -->|"RPUSH"| K8sRedis
        K8sRedis -->|"queue depth"| K8sKEDA
        K8sKEDA -->|"creates"| K8sJobs
        K8sJobs -->|"BLPOP"| K8sRedis
    end
```

---

## 6. Data Flow — Single File Through Redis Backend (worker mode)

```mermaid
sequenceDiagram
    participant UI as Client
    participant API as FastAPI
    participant PS as PipelineService
    participant RB as RedisBackend
    participant RQ as Redis Queue
    participant KEDA as KEDA
    participant Job as K8s Job Worker
    participant OS as OpenSearch

    UI->>API: POST /ingest (file)
    API->>PS: run_files([FileMetadata])
    PS->>RB: submit(pipeline, [fm])
    RB->>RQ: RPUSH pipeline:queue {batch_id, file, attempt:0}
    RB->>RQ: HSET pipeline:meta:{batch_id} total=1
    RB-->>PS: batch_id
    PS-->>UI: 202 { batch_id }

    RQ-->>KEDA: queue depth ≥ 1
    KEDA->>Job: create K8s Job
    Job->>RQ: BLPOP pipeline:queue
    Job->>Job: parse → chunk → embed

    alt success
        Job->>OS: opensearch _bulk
        Job->>RQ: HSET pipeline:results:{batch_id}
    else failure (attempt < max_retries)
        Job->>RQ: RPUSH pipeline:queue {attempt+1}
        Note over Job: exponential backoff sleep
    else exhausted (attempt == max_retries)
        Job->>RQ: RPUSH pipeline:dlq:{batch_id}
    end

    Job->>Job: exit 0 (memory released)
    KEDA->>KEDA: queue empty → 0 Jobs
```
