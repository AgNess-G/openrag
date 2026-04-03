"""Redis queue-based execution backend.

Two modes controlled by ``execution.redis.mode``:

local  (default)
    RedisBackend spawns N asyncio worker tasks that drain the global
    queue in-process.  Redis is still required (docker-compose redis
    service) but no external worker processes are needed.
    Mirrors the LocalBackend DX while adding retry + DLQ support and
    persistent batch state that survives an API-server restart.

worker
    RedisBackend only enqueues items and tracks progress via Redis.
    External workers — K8s Jobs triggered by KEDA — drain the queue.
    Use this mode inside the openrag-backend container when deploying
    to Kubernetes with the redis execution profile.

Redis key schema
----------------
pipeline:queue                  LIST   Global work queue (RPUSH / BLPOP)
pipeline:meta:{batch_id}        HASH   total, submitted_at
pipeline:inflight:{batch_id}    SET    file labels currently being processed
pipeline:results:{batch_id}     HASH   file_hash → PipelineResult JSON
pipeline:dlq:{batch_id}         LIST   Items exhausted all retries
pipeline:cancelled:{batch_id}   STRING Set to "1" when batch is cancelled
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pipeline.types import FileMetadata, PipelineResult
from utils.logging_config import get_logger

if TYPE_CHECKING:
    from pipeline.config import PipelineConfig
    from pipeline.pipeline import IngestionPipeline

logger = get_logger(__name__)

try:
    import redis.asyncio as aioredis

    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False

QUEUE_KEY = "pipeline:queue"


def _redis_url(cfg) -> str:
    if cfg.password:
        return f"redis://:{cfg.password}@{cfg.host}:{cfg.port}/{cfg.db}"
    return f"redis://{cfg.host}:{cfg.port}/{cfg.db}"


def _meta_key(batch_id: str) -> str:
    return f"pipeline:meta:{batch_id}"


def _inflight_key(batch_id: str) -> str:
    return f"pipeline:inflight:{batch_id}"


def _results_key(batch_id: str) -> str:
    return f"pipeline:results:{batch_id}"


def _dlq_key(batch_id: str) -> str:
    return f"pipeline:dlq:{batch_id}"


def _cancelled_key(batch_id: str) -> str:
    return f"pipeline:cancelled:{batch_id}"


class RedisBackend:
    """Queue-based execution backend using Redis."""

    def __init__(self, pipeline_config: PipelineConfig) -> None:
        if not _REDIS_AVAILABLE:
            raise ImportError(
                "redis[asyncio] is not installed. "
                "Add 'redis[asyncio]>=5.0' to your dependencies."
            )
        self._config = pipeline_config
        self._redis_cfg = pipeline_config.execution.redis
        self._r: aioredis.Redis | None = None
        # Worker asyncio Tasks created in local mode (one per concurrency slot)
        self._worker_tasks: list[asyncio.Task] = []

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    async def _redis(self) -> aioredis.Redis:
        if self._r is None:
            self._r = aioredis.from_url(
                _redis_url(self._redis_cfg),
                encoding="utf-8",
                decode_responses=True,
            )
        return self._r

    async def _set_batch_ttl(self, r: aioredis.Redis, batch_id: str) -> None:
        ttl = self._redis_cfg.result_ttl
        for key in (
            _meta_key(batch_id),
            _results_key(batch_id),
            _dlq_key(batch_id),
            _inflight_key(batch_id),
        ):
            await r.expire(key, ttl)

    # ------------------------------------------------------------------ #
    # ExecutionBackend protocol                                            #
    # ------------------------------------------------------------------ #

    async def submit(
        self,
        pipeline: IngestionPipeline,
        file_tasks: list[FileMetadata],
    ) -> str:
        batch_id = str(uuid.uuid4())
        r = await self._redis()
        cfg = self._redis_cfg

        # Persist batch metadata so get_progress() works across restarts
        await r.hset(
            _meta_key(batch_id),
            mapping={
                "total": len(file_tasks),
                "submitted_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        await self._set_batch_ttl(r, batch_id)

        # Enqueue one item per file
        if file_tasks:
            items = [
                json.dumps(
                    {
                        "batch_id": batch_id,
                        "file_hash": fm.file_hash,
                        "metadata": asdict(fm),
                        "attempt": 0,
                        "max_retries": cfg.max_retries,
                    }
                )
                for fm in file_tasks
            ]
            await r.rpush(QUEUE_KEY, *items)

        logger.info(
            "Redis backend: batch submitted",
            batch_id=batch_id,
            file_count=len(file_tasks),
            mode=cfg.mode,
        )

        if cfg.mode == "local":
            # Spawn asyncio workers — they drain the global queue and exit
            # when it is empty.  concurrency = execution.concurrency setting.
            concurrency = self._config.execution.concurrency
            for _ in range(concurrency):
                task = asyncio.create_task(
                    _worker_loop(r, pipeline, self._config)
                )
                self._worker_tasks.append(task)

        return batch_id

    async def get_progress(self, batch_id: str) -> dict:
        r = await self._redis()
        meta = await r.hgetall(_meta_key(batch_id))
        if not meta:
            raise KeyError(f"Unknown batch: {batch_id}")

        total = int(meta.get("total", 0))
        results_raw = await r.hgetall(_results_key(batch_id))
        dlq_raw = await r.lrange(_dlq_key(batch_id), 0, -1)
        inflight = list(await r.smembers(_inflight_key(batch_id)))

        results: list[PipelineResult] = []
        for raw_val in results_raw.values():
            data = json.loads(raw_val)
            results.append(PipelineResult(**data))

        # Surface DLQ entries as failed PipelineResults so callers see them
        for entry_raw in dlq_raw:
            entry = json.loads(entry_raw)
            fm_data = entry["file"]
            results.append(
                PipelineResult(
                    file_path=fm_data["file_path"],
                    document_id=fm_data["file_hash"],
                    filename=fm_data["filename"],
                    chunks_total=0,
                    chunks_indexed=0,
                    status="failed",
                    error=(
                        f"[DLQ after {entry['attempts']} attempt(s)] "
                        f"{entry['error']}"
                    ),
                )
            )

        failed = sum(1 for res in results if res.status == "failed")
        completed = sum(1 for res in results if res.status != "failed")

        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "in_flight": inflight,
            "results": results,
        }

    async def cancel(self, batch_id: str) -> None:
        r = await self._redis()
        await r.set(
            _cancelled_key(batch_id),
            "1",
            ex=self._redis_cfg.result_ttl,
        )
        for task in self._worker_tasks:
            if not task.done():
                task.cancel()
        logger.info("Redis backend: batch cancelled", batch_id=batch_id)

    async def wait_for_batch(self, batch_id: str) -> dict:
        """Block until all files in the batch are accounted for."""
        r = await self._redis()
        meta = await r.hgetall(_meta_key(batch_id))
        if not meta:
            raise KeyError(f"Unknown batch: {batch_id}")

        total = int(meta.get("total", 0))
        timeout = self._config.execution.timeout
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout

        while loop.time() < deadline:
            results_count = await r.hlen(_results_key(batch_id))
            dlq_count = await r.llen(_dlq_key(batch_id))
            if results_count + dlq_count >= total:
                break
            # In local mode we can also stop early if all workers have exited
            if self._worker_tasks and all(t.done() for t in self._worker_tasks):
                break
            await asyncio.sleep(1.0)

        return await self.get_progress(batch_id)

    async def close(self) -> None:
        if self._r is not None:
            await self._r.aclose()
            self._r = None


# ------------------------------------------------------------------ #
# Worker logic (shared between local asyncio tasks and job_worker.py) #
# ------------------------------------------------------------------ #


async def _worker_loop(
    r: aioredis.Redis,
    pipeline: IngestionPipeline,
    pipeline_config: PipelineConfig,
    *,
    idle_timeout: int = 5,
    max_items: int | None = None,
) -> None:
    """
    Pull items from the global queue and process them until it is empty.

    Used in two contexts:
    - Spawned as an asyncio Task by RedisBackend.submit() in local mode.
    - Called directly by job_worker.py inside a K8s Job container.

    Args:
        r:               Connected async Redis client.
        pipeline:        Built IngestionPipeline instance.
        pipeline_config: Full PipelineConfig (for retry settings).
        idle_timeout:    Seconds to wait on BLPOP before declaring the
                         queue empty and exiting.
        max_items:       Stop after processing this many items (tests).
    """
    processed = 0

    while True:
        if max_items is not None and processed >= max_items:
            break

        raw = await r.blpop(QUEUE_KEY, timeout=idle_timeout)
        if raw is None:
            # Queue is empty — worker exits gracefully
            logger.debug("Redis worker: queue empty, exiting")
            break

        try:
            item = json.loads(raw[1])
        except (json.JSONDecodeError, KeyError):
            logger.error("Redis worker: malformed queue item, skipping", raw=raw[1])
            continue

        await _process_item(r, pipeline, pipeline_config, item)
        processed += 1

    logger.debug("Redis worker: finished", processed=processed)


async def _process_item(
    r: aioredis.Redis,
    pipeline: IngestionPipeline,
    pipeline_config: PipelineConfig,
    item: dict,
) -> None:
    """
    Process one queue item.

    Failure tiers
    -------------
    1. status=="failed" AND attempt < max_retries
       → exponential backoff sleep, re-enqueue with attempt+1

    2. status=="failed" AND attempt >= max_retries
       → write to DLQ; result NOT written to results hash so callers
         can distinguish DLQ entries from normal results

    3. status=="success" | "skipped"
       → write to results hash
    """
    cfg = pipeline_config.execution.redis
    batch_id = item["batch_id"]
    attempt = item.get("attempt", 0)
    max_retries = item.get("max_retries", cfg.max_retries)

    fm = FileMetadata(**item["metadata"])
    label = fm.filename or fm.file_path

    # Short-circuit if the batch was cancelled
    if await r.exists(_cancelled_key(batch_id)):
        logger.info(
            "Redis worker: skipping cancelled batch",
            batch_id=batch_id,
            file=label,
        )
        return

    # Mark as in-flight so get_progress() can surface it
    await r.sadd(_inflight_key(batch_id), label)

    try:
        logger.info(
            "Redis worker: processing",
            batch_id=batch_id,
            file=label,
            attempt=attempt,
        )
        result = await pipeline.run(fm.file_path, fm)
    finally:
        await r.srem(_inflight_key(batch_id), label)

    if result.status == "failed" and attempt < max_retries:
        backoff = min(
            cfg.retry_backoff_base * (2**attempt),
            cfg.retry_backoff_max,
        )
        logger.warning(
            "Redis worker: transient failure — retrying",
            batch_id=batch_id,
            file=label,
            attempt=attempt,
            next_attempt=attempt + 1,
            backoff_s=backoff,
            error=result.error,
        )
        await asyncio.sleep(backoff)
        item["attempt"] = attempt + 1
        await r.rpush(QUEUE_KEY, json.dumps(item))
        return

    if result.status == "failed":
        logger.error(
            "Redis worker: permanent failure → DLQ",
            batch_id=batch_id,
            file=label,
            attempts=attempt + 1,
            error=result.error,
        )
        await r.rpush(
            _dlq_key(batch_id),
            json.dumps(
                {
                    "file": asdict(fm),
                    "error": result.error,
                    "attempts": attempt + 1,
                }
            ),
        )
        return

    # success or skipped — write to results hash
    await r.hset(
        _results_key(batch_id),
        fm.file_hash,
        json.dumps(asdict(result)),
    )

    logger.info(
        "Redis worker: file done",
        batch_id=batch_id,
        file=label,
        status=result.status,
        chunks_indexed=result.chunks_indexed,
        duration_s=round(result.duration_seconds, 2),
    )
