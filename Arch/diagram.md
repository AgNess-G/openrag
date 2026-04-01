# OpenRAG Ingestion Architecture — Evolution Diagram

Compares three generations of the ingestion architecture: the original dual-path system, the first composable design (Redis-backed), and the final composable design (Ray-backed).

---

## 1. Generation 1 — Original Dual-Path Architecture

The baseline before the composable pipeline. Two hardcoded paths, no pluggable stages, all in-process.

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

## 2. Generation 2 — Composable Pipeline · Arch 1 (Redis Streams)

Introduced a protocol-based pluggable pipeline. Proposed Redis Streams as the durable work queue.

```mermaid
flowchart TB
    Client(["Client\nFile Upload"])

    subgraph api [API Layer]
        Upload["POST /ingest"]
        Switch{"ingestion_mode?"}
    end

    subgraph existing [Existing Paths — Untouched]
        Langflow["Langflow Pipeline"]
        Traditional["Traditional Pipeline"]
    end

    subgraph queue [Work Queue — Redis Streams]
        Redis[("Redis Streams\nDurable queue\nSeparate service")]
    end

    subgraph workers [Worker Pool]
        W1["Worker 1"]
        W2["Worker 2"]
        WN["Worker N"]
    end

    subgraph pipeline [Composable Pipeline — Per Worker]
        direction LR
        Parser["Parser\nauto | docling\nmarkitdown | text"]
        Pre["Preprocessors\ncleaning | dedup\nmetadata"]
        Chunker["Chunker\nrecursive | semantic\ncharacter | docling_hybrid"]
        Embedder["Embedder\nopenai | watsonx\nollama | huggingface"]
        Indexer["Indexer\nopensearch_bulk"]
        Parser --> Pre --> Chunker --> Embedder --> Indexer
    end

    subgraph cfg [Config — pipeline.yaml]
        YAML["version, ingestion_mode\nparser, preprocessors\nchunker, embedder\nindexer, execution"]
    end

    Client --> Upload --> Switch
    Switch -->|"langflow"| Langflow
    Switch -->|"traditional"| Traditional
    Switch -->|"composable"| Redis
    Redis --> W1 & W2 & WN
    W1 & W2 & WN --> Parser
    cfg -.->|"drives"| pipeline
```

**Why Redis was rejected:**
| Concern | Redis Streams |
|---|---|
| Local dev | Requires a running Redis server — extra infra |
| GPU scheduling | None — no awareness of compute resources |
| ML workloads | Not designed for compute orchestration |
| Monitoring | External tooling needed |
| Moving parts | Redis + consumer group logic |

---

## 3. Generation 3 — Composable Pipeline · Arch 2 (Ray)

Replaced Redis with Ray. Same pluggable stage design; execution backend is now an abstraction with two implementations.

```mermaid
flowchart TB
    Client(["Client\nFile Upload"])

    subgraph api [API Layer]
        Upload["POST /ingest"]
        TaskSvc["TaskService\n+ ComposableFileProcessor\nfull /tasks tracking"]
        Switch{"ingestion_mode?"}
    end

    subgraph existing [Existing Paths — Untouched]
        Langflow["Langflow Pipeline"]
        Traditional["Traditional Pipeline"]
    end

    subgraph backend_choice [Execution Backend — pipeline.yaml]
        BackendSwitch{"execution.backend?"}
    end

    subgraph local_backend [local — Default · Zero Infra]
        LocalSem["asyncio.Semaphore\nexecution.concurrency\nin-process"]
    end

    subgraph ray_backend [ray — Scalable · Distributed]
        RayInit["ray.init\nauto | address"]
        subgraph ray_cluster [Ray Cluster]
            RayHead["Ray Head\nGCS + Dashboard :8265"]
            RayW1["Ray Worker 1\nisolated process"]
            RayW2["Ray Worker 2\nisolated process"]
            RayWN["Ray Worker N\nisolated process"]
            RayHead --> RayW1 & RayW2 & RayWN
        end
        RayInit --> RayHead
    end

    subgraph pipeline [Composable Pipeline — Rebuilt per Worker]
        direction LR
        Parser2["Parser\nauto | docling\nmarkitdown | text"]
        Pre2["Preprocessors\ncleaning | dedup\nmetadata"]
        Chunker2["Chunker\nrecursive | semantic\ncharacter | docling_hybrid"]
        Embedder2["Embedder\nopenai | watsonx\nollama | huggingface"]
        Indexer2["Indexer\nopensearch_bulk"]
        Parser2 --> Pre2 --> Chunker2 --> Embedder2 --> Indexer2
    end

    subgraph cfg2 [Config — pipeline.yaml]
        YAML2["ingestion_mode: composable\nexecution:\n  backend: local | ray\n  concurrency: N\n  ray:\n    address: auto"]
    end

    Client --> Upload --> TaskSvc --> Switch
    Switch -->|"langflow"| Langflow
    Switch -->|"traditional"| Traditional
    Switch -->|"composable"| BackendSwitch
    BackendSwitch -->|"local"| LocalSem
    BackendSwitch -->|"ray"| RayInit
    LocalSem --> Parser2
    RayW1 & RayW2 & RayWN --> Parser2
    cfg2 -.->|"drives"| pipeline
    cfg2 -.->|"drives"| BackendSwitch
```

---

## 4. Side-by-Side Comparison

```mermaid
flowchart LR
    subgraph gen1 [Gen 1 — Dual Path]
        direction TB
        G1A["Upload"]
        G1B{"DISABLE_\nLANGFLOW?"}
        G1C["Langflow\nhardcoded stages"]
        G1D["Traditional\nhardcoded stages"]
        G1E["asyncio.Semaphore\nin-process only"]
        G1A --> G1B
        G1B -->|false| G1C
        G1B -->|true| G1D
        G1C & G1D --> G1E
    end

    subgraph gen2 [Gen 2 — Composable + Redis]
        direction TB
        G2A["Upload"]
        G2B{"ingestion_mode?"}
        G2C["Langflow / Traditional\nunchanged"]
        G2D[("Redis Streams\nexternal service")]
        G2E["Worker Pool\npluggable stages"]
        G2A --> G2B
        G2B -->|"langflow/traditional"| G2C
        G2B -->|"composable"| G2D --> G2E
    end

    subgraph gen3 [Gen 3 — Composable + Ray]
        direction TB
        G3A["Upload → TaskService\n/tasks tracking"]
        G3B{"ingestion_mode?"}
        G3C["Langflow / Traditional\nunchanged"]
        G3D{"execution.backend?"}
        G3E["LocalBackend\nasyncio · zero deps"]
        G3F["RayBackend\ndistributed · GPU-aware"]
        G3G["Pluggable stages\nrebuilt per worker\nPipelineConfig only"]
        G3A --> G3B
        G3B -->|"langflow/traditional"| G3C
        G3B -->|"composable"| G3D
        G3D -->|"local"| G3E --> G3G
        G3D -->|"ray"| G3F --> G3G
    end
```

---

## 5. Key Decisions — Why Ray Beat Redis

| Concern | Gen 1 (asyncio only) | Gen 2 (Redis Streams) | Gen 3 (Ray) |
|---|---|---|---|
| Local dev infra | None (in-process) | Redis server required | `ray.init()` — zero external services |
| Task durability | None — lost on restart | Durable in Redis | Ray object store + lineage |
| GPU scheduling | None | None | Native — place on GPU node |
| Fault tolerance | None | Manual consumer retry | Built-in retries + lineage |
| Monitoring | None | External tooling | Ray Dashboard bundled (:8265) |
| Cloud/K8s scale | Not possible | Needs Redis cluster | KubeRay on IKS/Code Engine |
| ML workloads | Poor | Poor | Designed for it |
| `/tasks` API tracking | TaskService | Not wired | TaskService (same as gen 1) |
| Serialization concern | N/A | N/A | Config dict only (no pickle of HTTP clients) |

---

## 6. Deployment Topology — Ray Backend Only

```mermaid
flowchart TB
    subgraph local_dev [Local Dev · ray.init auto]
        DevApp["openrag-backend\n+ Ray head\n(same process)"]
    end

    subgraph docker [Docker Compose · --profile ray]
        DocApp["openrag-backend"]
        DocHead["ray-head :6379 :8265"]
        DocWorkers["ray-worker × N\n(langflowai/openrag-backend image)"]
        DocApp -->|"ray://ray-head:10001"| DocHead
        DocHead --> DocWorkers
    end

    subgraph iks [IBM Cloud IKS · KubeRay]
        IKSApp["openrag-backend pod"]
        IKSHead["RayCluster head"]
        IKSCPU["cpu-workers\nautoscale 1–20"]
        IKSGPU["gpu-workers\nIKS GPU pool"]
        IKSApp -->|"ray://head-svc:10001"| IKSHead
        IKSHead --> IKSCPU & IKSGPU
    end

    subgraph ce [IBM Code Engine · Serverless]
        CEApp["openrag-backend app"]
        CEHead["ray-head app\n(fixed scale 1)"]
        CEWorkers["ray-workers job\n(scale 0 → N)"]
        CEApp -->|"private endpoint"| CEHead
        CEHead --> CEWorkers
    end
```

---

## 7. Data Flow — Single File Through Ray Backend

```mermaid
sequenceDiagram
    participant UI as Client
    participant API as FastAPI
    participant TS as TaskService
    participant CFP as ComposableFileProcessor
    participant PS as PipelineService
    participant RB as RayBackend
    participant RW as Ray Worker (isolated process)
    participant OS as OpenSearch

    UI->>API: POST /ingest (file)
    API->>TS: create_langflow_upload_task()
    TS-->>UI: 202 { task_id }
    TS->>CFP: process_all_items(upload_task, [file])

    CFP->>PS: run_files([FileMetadata])
    PS->>RB: submit(pipeline, [fm])
    Note over RB: serialises PipelineConfig as dict<br/>no HTTP clients / locks pickled
    RB-->>PS: batch_id
    PS-->>CFP: batch_id

    CFP->>PS: wait_for_batch(batch_id)
    PS->>RB: wait_for_batch(batch_id)

    RB->>RW: ray.remote(config_dict, file_path, metadata_dict)
    Note over RW: rebuilds PipelineConfig<br/>initialises fresh OpenSearch client<br/>(new event loop per task)
    RW->>RW: parse → preprocess → chunk → embed
    RW->>OS: opensearch_bulk _bulk
    OS-->>RW: indexed
    RW-->>RB: PipelineResult

    RB-->>PS: progress dict
    PS-->>CFP: progress dict
    CFP->>TS: file_task.status = COMPLETED\nchunks_indexed, duration_seconds

    UI->>API: GET /tasks/{task_id}
    API->>TS: get_task_status()
    TS-->>UI: { status, files, chunks_indexed, ... }
```
