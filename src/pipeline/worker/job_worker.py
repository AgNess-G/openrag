"""
Pipeline Job Worker
===================
Standalone entry point that drains the Redis work queue and runs the
ingestion pipeline on each item.

Runs in two contexts
--------------------
1. **Local mode** — spawned as asyncio Tasks inside the API process by
   RedisBackend when ``execution.redis.mode = local``.  You do not invoke
   this module directly in that case; it is called programmatically via
   ``pipeline.execution.redis_backend._worker_loop``.

2. **K8s Job mode** — executed as the container entrypoint of an ephemeral
   Kubernetes Job created by KEDA.  One Job processes items until the queue
   is empty, then exits and releases all memory.

Usage (K8s Job / manual test)
------------------------------
    python -m pipeline.worker.job_worker

Environment variables
---------------------
REDIS_HOST          Redis hostname       (default: localhost)
REDIS_PORT          Redis port           (default: 6379)
REDIS_PASSWORD      Redis password       (default: none)
REDIS_DB            Redis logical DB     (default: 0)
PIPELINE_CONFIG_FILE  Path to YAML preset  (default: built-in pipeline.yaml)
PIPELINE_EXECUTION_*  Any pipeline config override

The worker respects all PIPELINE_* env var overrides defined in
pipeline.config._ENV_OVERRIDES, so it picks up the same embedder,
chunker, parser, etc. as the API server without any extra config.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import asdict

from pipeline.config import PipelineConfigManager
from pipeline.execution.redis_backend import (
    QUEUE_KEY,
    _cancelled_key,
    _dlq_key,
    _inflight_key,
    _process_item,
    _redis_url,
    _results_key,
)
from pipeline.pipeline import PipelineBuilder
from pipeline.registry import get_default_registry
from pipeline.types import FileMetadata
from utils.logging_config import get_logger

logger = get_logger(__name__)

# How long to wait for a new queue item before deciding the queue is empty
# and exiting.  Set higher than the API-server's retry backoff max to avoid
# a worker exiting prematurely while items are sleeping in backoff.
_IDLE_TIMEOUT_SECONDS = int(os.getenv("WORKER_IDLE_TIMEOUT", "15"))


async def main() -> int:
    """
    Entry point for the K8s Job container.

    Returns
    -------
    int
        Exit code: 0 = success, 1 = startup failure.
    """
    # ── Load config ───────────────────────────────────────────────────
    cfg_manager = PipelineConfigManager()
    pipeline_config = cfg_manager.load()
    redis_cfg = pipeline_config.execution.redis

    redis_url = _redis_url(redis_cfg)
    safe_url = redis_url.split("@")[-1]  # strip password from logs

    logger.info("Pipeline job worker starting", redis=safe_url)

    # ── Connect to Redis ──────────────────────────────────────────────
    try:
        import redis.asyncio as aioredis
    except ImportError:
        logger.error(
            "redis[asyncio] not installed — add 'redis[asyncio]>=5.0' to dependencies"
        )
        return 1

    r = aioredis.from_url(redis_url, encoding="utf-8", decode_responses=True)

    # ── Build pipeline ────────────────────────────────────────────────
    # Import here so startup failures surface clearly before entering the loop
    try:
        from config.settings import clients  # type: ignore[import]

        await clients.initialize()
        os_client = getattr(clients, "opensearch", None)
    except Exception as exc:
        logger.error("Worker: failed to initialise OpenSearch client", error=str(exc))
        os_client = None

    registry = get_default_registry()
    builder = PipelineBuilder(pipeline_config, registry)
    pipeline = builder.build(opensearch_client=os_client)

    logger.info(
        "Pipeline job worker ready",
        backend=pipeline_config.execution.backend,
        parser=pipeline_config.parser.type,
        chunker=pipeline_config.chunker.type,
        embedder=pipeline_config.embedder.provider,
        idle_timeout=_IDLE_TIMEOUT_SECONDS,
    )

    # ── Drain the queue ───────────────────────────────────────────────
    processed = 0

    try:
        while True:
            raw = await r.blpop(QUEUE_KEY, timeout=_IDLE_TIMEOUT_SECONDS)

            if raw is None:
                logger.info(
                    "Worker: queue empty — exiting",
                    items_processed=processed,
                )
                break

            try:
                item = json.loads(raw[1])
            except (json.JSONDecodeError, KeyError) as exc:
                logger.error(
                    "Worker: malformed queue item — skipping",
                    error=str(exc),
                    raw=raw[1][:200],
                )
                continue

            await _process_item(r, pipeline, pipeline_config, item)
            processed += 1

    finally:
        # Release OpenSearch connections before the process exits so the
        # container terminates cleanly (no "Unclosed client session" warnings).
        try:
            if os_client is not None:
                await os_client.close()
        except Exception:
            pass
        await r.aclose()

    logger.info("Pipeline job worker finished", items_processed=processed)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
