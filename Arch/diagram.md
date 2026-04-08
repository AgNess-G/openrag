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

## 4. TLS Boundaries — Gen 3

Where TLS is required, what encrypts what, and current implementation status.

```mermaid
flowchart TB
    Browser(["Browser / API Client"])

    subgraph ingress [Layer 1 — Ingress TLS ⚠ not yet implemented]
        LB["Load Balancer\n(IBM VPC LB / nginx ingress)"]
        TLSNote["cert-manager + Let's Encrypt\nor IBM Certificate Manager\nStatus: planned"]
    end

    subgraph api_tier [API Tier]
        Backend["openrag-backend\nFastAPI :8000"]
        Frontend["openrag-frontend\nNext.js :3000"]
    end

    subgraph layer2 [Layer 2 — OpenSearch TLS ⚠ verify_certs=False]
        OS[("OpenSearch :9200\nself-signed cert\nsettings.py:366,841")]
        OSNote["verify_certs=False today\nNeeds: OPENSEARCH_CA_CERT_PATH\n+ OPENSEARCH_VERIFY_CERTS=true"]
    end

    subgraph layer3 [Layer 3 — Redis TLS ⚠ not yet implemented]
        Redis[("IBM Databases for Redis\nrediss:// enforced")]
        RedisNote["Current code: redis:// plain\nNeeds: rediss:// + SSLContext\nconfig.py RedisConfig.tls\nredis_backend._build_ssl_context()"]
    end

    subgraph layer4 [Layer 4 — mTLS pod-to-pod ✗ not planned]
        Mesh["Service Mesh\n(Istio / Linkerd)\nSkipped: high ops overhead\nfor marginal gain"]
    end

    Browser -->|"HTTP (plain) today"| LB
    LB --> Frontend & Backend
    Backend -->|"HTTPS, verify=False"| OS
    Backend -->|"redis:// plain today"| Redis
    layer4 -.->|"optional future"| api_tier
```

**Priority order to fix:**
1. Redis TLS — `rediss://` + `_build_ssl_context()` — code change, 4 files
2. OpenSearch `verify_certs` — env-var controlled, 2 lines
3. Ingress TLS — cert-manager + ingress manifest — infra change
4. mTLS — skip unless compliance requires it

---

## 5. IBM Cloud Deployment — Gen 3

Full production topology on IBM Cloud with IKS + KEDA + IBM Databases for Redis.

```mermaid
flowchart TB
    Internet(["Internet"])

    subgraph ibm_cloud [IBM Cloud — us-south]

        subgraph vpc [VPC]
            LB["VPC Load Balancer\n(public IP)\nIBM Cloud annotation"]

            subgraph iks [IKS Cluster]
                subgraph openrag_ns [namespace: openrag]
                    FE["openrag-frontend\nDeployment × 2\nHPA: cpu"]
                    BE["openrag-backend\nDeployment × 2\nScaledObject: cpu + queue"]
                    OS_Pod[("OpenSearch\nStatefulSet × 1\nPVC: ibmc-vpc-block-10iops")]
                end

                subgraph keda_ns [namespace: keda]
                    KEDA["KEDA operator\nScaledJob watcher"]
                end

                subgraph spot_pool [Worker Pool: pipeline-spot]
                    J1["K8s Job 1\njob_worker.py\nspot node"]
                    J2["K8s Job 2\njob_worker.py\nspot node"]
                    JN["K8s Job N\njob_worker.py\nspot node"]
                end
            end
        end

        subgraph managed [IBM Managed Services]
            Redis[("IBM Databases\nfor Redis\nTLS enforced\nprivate endpoint")]
            ICR["IBM Container\nRegistry\nimage pull"]
        end

    end

    Internet -->|"HTTPS"| LB
    LB --> FE --> BE
    BE -->|"RPUSH\nrediss://"| Redis
    Redis -->|"queue depth"| KEDA
    KEDA -->|"creates Jobs"| J1 & J2 & JN
    J1 & J2 & JN -->|"BLPOP\nrediss://"| Redis
    J1 & J2 & JN -->|"HTTPS\nbulk index"| OS_Pod
    BE -->|"HTTPS\nquery"| OS_Pod
    IKS -.->|"pull image"| ICR
```

**Terraform provisions:** VPC, IKS cluster, spot worker pool, IBM Databases for Redis, IBM Container Registry namespace, K8s namespace/secrets/deployments, KEDA via Helm, ScaledJob + ScaledObject.

**IBM COS note:** Not provisioned as platform infra. IBM COS is a *connector* — users supply their own bucket credentials via the UI. OpenRAG reads documents from it and indexes vectors into OpenSearch.

---

## 6. Retrieval Pipeline — Current Architecture

The retrieval side mirrors the ingestion pipeline's composable design. Every
stage (retriever, reranker, agent, tools, nudges) is pluggable via YAML config
and env-var overrides.

### 6a. Component Overview

```mermaid
flowchart TB
    Client(["Browser\n/ API Client"])

    subgraph api [API Layer]
        ChatEP["POST /chat\nlangflow_endpoint()"]
        DisableFlag{"DISABLE_LANGFLOW?"}
    end

    subgraph chat_service [ChatService]
        ComposableStream["composable_chat_stream()"]
        PipelineMgr["RetrievalPipelineManager\n(singleton)"]
    end

    subgraph config [Config — YAML + Env Overrides]
        YAMLFile["RETRIEVAL_CONFIG_FILE\nretrieval.yaml (default)\nretrieval-react.yaml\nretrieval-deep.yaml"]
        EnvOverrides["RETRIEVAL_AGENT_TYPE\nRETRIEVAL_AGENT_MODEL\nRETRIEVAL_RETRIEVER_TYPE\nRETRIEVAL_RERANKER_TYPE\nRETRIEVAL_ROLLING_WINDOW"]
        Builder["RetrievalPipelineBuilder\n(reads config + registry)"]
        YAMLFile --> Builder
        EnvOverrides --> Builder
    end

    subgraph pipeline [RetrievalPipeline — per request]
        direction LR
        ConvLoad["ConversationManager\nget_history()\nrolling window N msgs"]
        Retriever["Retriever\nhybrid | vector\nkeyword | raw"]
        Reranker["Reranker\nnone | cohere\ncross_encoder"]
        Agent["Agent\nopenai | react | deep"]
        ConvStore["ConversationManager\nstore()"]
        ConvLoad --> Retriever --> Reranker --> Agent --> ConvStore
    end

    subgraph storage [Storage]
        OS[("OpenSearch\nVector Index\n+ KNN")]
        ConvFile[("conversations.json\nper-user thread")]
    end

    subgraph tools [Composable Tools — ReAct / Deep only]
        T1["hybrid_search"]
        T2["semantic_search"]
        T3["keyword_search"]
        T4["raw_search"]
        T5["get_document"]
        T6["list_sources"]
        T7["calculator"]
    end

    Client -->|"SSE / NDJSON"| ChatEP
    ChatEP --> DisableFlag
    DisableFlag -->|"true"| ComposableStream
    DisableFlag -->|"false"| LangflowPath["Langflow path\n(legacy)"]
    ComposableStream --> PipelineMgr
    PipelineMgr -->|"first call"| Builder
    Builder -->|"builds"| pipeline

    ConvLoad <-->|"read thread"| ConvFile
    Retriever -->|"KNN + multi_match\nbool.filter"| OS
    Agent -->|"tool calls\n(jwt_token + user_id)"| tools
    tools -->|"OpenSearch queries"| OS
    ConvStore -->|"write thread"| ConvFile
```

---

### 6b. Agent Modes

Three interchangeable agent implementations, selected via `agent.type` in YAML.

```mermaid
flowchart TB
    subgraph openai_agent ["agent.type: openai — Default"]
        OA_In["query + context\n+ history"]
        OA_LLM["OpenAI Chat Completions\nchat.completions.create(stream=True)\nstream_options: include_usage"]
        OA_Out["stream: {delta} chunks\n+ {response.completed, usage}"]
        OA_In --> OA_LLM --> OA_Out
    end

    subgraph react_agent ["agent.type: react — Multi-hop"]
        RA_In["query + context\n+ history"]
        RA_Prompt["ReAct Prompt\n(Thought → Action → Observation loop)"]
        RA_LLM["ChatOpenAI\nLangChain AgentExecutor"]
        RA_Tools["Tool calls\non_tool_start → on_tool_end\nevents streamed to client"]
        RA_Out["stream: {delta} + {tool_call added/done}\n+ {response.completed, usage}"]
        RA_In --> RA_Prompt --> RA_LLM
        RA_LLM <-->|"astream_events v2"| RA_Tools
        RA_LLM --> RA_Out
    end

    subgraph deep_agent ["agent.type: deep — Research / Planning"]
        DA_In["query + context\n+ history"]
        DA_SDK["deepagents.create_deep_agent\nLangGraph + write_todos\n+ subagent spawning"]
        DA_Tools["Tool calls\non_tool_start → on_tool_end\nevents streamed to client"]
        DA_Out["stream: {delta} + {tool_call added/done}\n+ {response.completed, usage}"]
        DA_In --> DA_SDK
        DA_SDK <-->|"astream_events v2"| DA_Tools
        DA_SDK --> DA_Out
    end

    Config["RETRIEVAL_AGENT_TYPE\nor agent.type in YAML"] -->|"selects"| openai_agent & react_agent & deep_agent
```

---

### 6c. Streaming Data Flow — Chat Request

```mermaid
sequenceDiagram
    participant UI as Browser
    participant API as FastAPI
    participant CS as ChatService
    participant PM as PipelineManager
    participant CM as ConvManager
    participant RTV as Retriever
    participant RR as Reranker
    participant AG as Agent
    participant OS as OpenSearch

    UI->>API: POST /chat {prompt, previous_response_id}
    API->>CS: composable_chat_stream()
    CS->>PM: get_pipeline() [singleton]
    PM-->>CS: RetrievalPipeline

    CS->>CM: get_history(user_id, prev_response_id)
    CM-->>CS: last N ConversationMessages

    CS->>RTV: retrieve(RetrievalQuery)
    RTV->>OS: KNN + multi_match query
    OS-->>RTV: top-K docs
    RTV-->>CS: list[SearchResult]

    CS->>RR: rerank(query, results)
    RR-->>CS: reordered list[SearchResult]

    CS->>AG: run_stream(query, results, history)

    loop Streaming tokens + tool events
        AG-->>UI: {"delta": "token"}\n
        AG-->>UI: {"type":"response.output_item.added","item":{tool_call, inputs}}\n
        AG->>OS: tool query (hybrid/semantic/keyword)
        OS-->>AG: tool results
        AG-->>UI: {"type":"response.output_item.done","item":{tool_call, results}}\n
    end

    AG-->>UI: {"type":"response.completed","response":{"usage":{...}}}\n

    CS->>CM: store(user_id, response_id, query, response)
    CS-->>UI: {"response_id":"...","sources":[...],"usage":{...}}\n
```

---

### 6d. Retriever Options

```mermaid
flowchart LR
    subgraph retrievers [Retriever — retriever.type]
        Hybrid["hybrid\nDis-Max: 70% KNN + 30% multi_match\nprefix fallback\n(default)"]
        Vector["vector\nPure KNN\n(semantic only)"]
        Keyword["keyword\nPure multi_match\n(exact / fuzzy)"]
        Raw["raw\nFull DSL passthrough\ncustom bool.filter"]
    end

    subgraph rerankers [Reranker — reranker.type]
        None["none\nPass-through\n(default)"]
        Cohere["cohere\nCohere Rerank API\nrerank-english-v3.0"]
        CrossEncoder["cross_encoder\nLocal sentence-transformers\nno API key needed"]
    end

    RETRIEVAL_RETRIEVER_TYPE --> retrievers
    RETRIEVAL_RERANKER_TYPE --> rerankers
    retrievers --> OS[("OpenSearch")]
    rerankers -->|"top_k results"| Agent
```

---

### 6e. Config Preset Matrix

| Preset file | Agent | Retriever | Reranker | Use case |
|---|---|---|---|---|
| `retrieval.yaml` | openai | hybrid | none | Default — fast, no tool use |
| `retrieval-react.yaml` | react | hybrid | none | Multi-hop tool calling |
| `retrieval-deep.yaml` | deep | hybrid | none | Research + planning tasks |

**Env overrides (take precedence over YAML):**

| Env var | Controls | Example |
|---|---|---|
| `RETRIEVAL_CONFIG_FILE` | Which preset to load | `src/pipeline/presets/retrieval/retrieval-react.yaml` |
| `RETRIEVAL_AGENT_TYPE` | `agent.type` | `react` |
| `RETRIEVAL_AGENT_MODEL` | `agent.model` | `gpt-4o` |
| `RETRIEVAL_RETRIEVER_TYPE` | `retriever.type` | `hybrid` |
| `RETRIEVAL_RERANKER_TYPE` | `reranker.type` | `none` |
| `RETRIEVAL_ROLLING_WINDOW` | Conversation history depth | `20` |

---

## 7. Comparison — All Three Generations

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

## 8. Deployment Topology — Gen 3

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

## 9. Data Flow — Single File Through Redis Backend (worker mode)

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
