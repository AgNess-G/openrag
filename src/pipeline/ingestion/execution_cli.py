"""CLI for composable ingestion execution via configured backend (local or Redis).

Commands
--------
submit <path>       Submit file(s) to the configured execution backend and wait for results.
                    Use --no-wait to return immediately with the batch_id (Redis only).
status <batch_id>   Poll progress for a previously submitted batch (Redis backend).
cancel <batch_id>   Cancel a running batch (Redis backend).
worker              Run as a Redis queue worker (for external/K8s worker mode).

Usage
-----
    uv run python -m pipeline.ingestion.execution_cli submit ./docs/
    uv run python -m pipeline.ingestion.execution_cli submit report.pdf --no-wait
    uv run python -m pipeline.ingestion.execution_cli status <batch_id>
    uv run python -m pipeline.ingestion.execution_cli cancel <batch_id>
    uv run python -m pipeline.ingestion.execution_cli worker

Or via the installed script entry point:
    openrag-ingest submit ./docs/
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import mimetypes
import os
import sys


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _file_metadata(file_path: str):
    from pipeline.ingestion.types import FileMetadata

    stat = os.stat(file_path)
    with open(file_path, "rb") as f:
        file_hash = hashlib.sha256(f.read()).hexdigest()

    mt, _ = mimetypes.guess_type(file_path)
    return FileMetadata(
        file_path=os.path.abspath(file_path),
        filename=os.path.basename(file_path),
        file_hash=file_hash,
        file_size=stat.st_size,
        mimetype=mt or "application/octet-stream",
    )


def _collect_paths(path: str, recursive: bool) -> list[str]:
    if os.path.isfile(path):
        return [path]
    paths: list[str] = []
    for root, _, files in os.walk(path):
        paths.extend(os.path.join(root, f) for f in files)
        if not recursive:
            break
    return paths


def _print_results(progress: dict) -> None:
    for r in progress["results"]:
        status = "OK" if r.status == "success" else r.status.upper()
        err = f" - {r.error}" if r.error else ""
        print(
            f"[{status}] {r.filename}: "
            f"{r.chunks_indexed}/{r.chunks_total} chunks, "
            f"{r.duration_seconds:.1f}s{err}"
        )
    total = progress["total"]
    ok = progress["completed"]
    fail = progress["failed"]
    print(f"\nDone: {ok}/{total} succeeded, {fail} failed.")


def _build_backend(config):
    """Instantiate the correct execution backend from config."""
    backend_type = config.execution.backend

    if backend_type == "redis":
        from pipeline.ingestion.execution.redis_backend import RedisBackend
        return RedisBackend(config)

    from pipeline.ingestion.execution.local_backend import LocalBackend
    return LocalBackend(concurrency=config.execution.concurrency)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

async def _cmd_submit(args: argparse.Namespace) -> None:
    from pipeline.ingestion.config import PipelineConfigManager
    from pipeline.ingestion.pipeline import PipelineBuilder
    from pipeline.ingestion.registry import get_default_registry

    config = PipelineConfigManager(args.config).load()
    config.ingestion_mode = "composable"

    paths = _collect_paths(args.path, args.recursive)
    if not paths:
        print("No files found.")
        return

    metas = [_file_metadata(p) for p in paths]
    print(f"Submitting {len(metas)} file(s) via '{config.execution.backend}' backend...")

    registry = get_default_registry()
    pipeline = PipelineBuilder(config, registry).build()
    backend = _build_backend(config)

    batch_id = await backend.submit(pipeline, metas)
    print(f"Batch ID: {batch_id}")

    if args.no_wait:
        print("Use `status <batch_id>` to check progress.")
        return

    # Wait for completion
    if hasattr(backend, "wait_for_batch"):
        progress = await backend.wait_for_batch(batch_id)
    else:
        # LocalBackend: gather the tasks directly
        import asyncio as _asyncio
        tasks = getattr(backend, "_batches", {}).get(batch_id, None)
        if tasks is not None:
            await _asyncio.gather(*tasks.tasks, return_exceptions=True)
        progress = await backend.get_progress(batch_id)

    _print_results(progress)

    if hasattr(backend, "close"):
        await backend.close()


async def _cmd_status(args: argparse.Namespace) -> None:
    from pipeline.ingestion.config import PipelineConfigManager

    config = PipelineConfigManager(args.config).load()
    if config.execution.backend != "redis":
        print("Error: `status` is only available for the Redis backend.")
        sys.exit(1)

    from pipeline.ingestion.execution.redis_backend import RedisBackend
    backend = RedisBackend(config)

    try:
        progress = await backend.get_progress(args.batch_id)
    except KeyError:
        print(f"Error: batch '{args.batch_id}' not found (may have expired).")
        sys.exit(1)

    total = progress["total"]
    ok = progress["completed"]
    fail = progress["failed"]
    inflight = progress.get("in_flight", [])

    print(f"Batch:    {args.batch_id}")
    print(f"Total:    {total}")
    print(f"Done:     {ok + fail}/{total}  ({ok} OK, {fail} failed)")
    if inflight:
        print(f"In-flight: {', '.join(inflight)}")

    if progress["results"]:
        print()
        _print_results(progress)

    await backend.close()


async def _cmd_cancel(args: argparse.Namespace) -> None:
    from pipeline.ingestion.config import PipelineConfigManager

    config = PipelineConfigManager(args.config).load()
    if config.execution.backend != "redis":
        print("Error: `cancel` is only available for the Redis backend.")
        sys.exit(1)

    from pipeline.ingestion.execution.redis_backend import RedisBackend
    backend = RedisBackend(config)
    await backend.cancel(args.batch_id)
    print(f"Cancelled batch: {args.batch_id}")
    await backend.close()


async def _cmd_worker(args: argparse.Namespace) -> None:
    """Run as an external Redis queue worker (for K8s / worker-mode deployments)."""
    from pipeline.ingestion.config import PipelineConfigManager
    from pipeline.ingestion.pipeline import PipelineBuilder
    from pipeline.ingestion.registry import get_default_registry

    config = PipelineConfigManager(args.config).load()
    if config.execution.backend != "redis":
        print("Error: `worker` requires backend=redis in config.")
        sys.exit(1)

    import redis.asyncio as aioredis
    from pipeline.ingestion.execution.redis_backend import (
        RedisBackend,
        _redis_url,
        _worker_loop,
    )

    config.ingestion_mode = "composable"
    registry = get_default_registry()
    pipeline = PipelineBuilder(config, registry).build()

    backend = RedisBackend(config)
    r = await backend._redis()

    print(
        f"Worker started — draining queue '{backend._redis_cfg.host}:{backend._redis_cfg.port}' "
        f"(concurrency={config.execution.concurrency}, idle_timeout={args.idle_timeout}s)"
    )

    concurrency = config.execution.concurrency
    tasks = [
        asyncio.create_task(
            _worker_loop(r, pipeline, config, idle_timeout=args.idle_timeout)
        )
        for _ in range(concurrency)
    ]

    try:
        await asyncio.gather(*tasks)
    except (KeyboardInterrupt, asyncio.CancelledError):
        for t in tasks:
            t.cancel()

    await backend.close()
    print("Worker stopped.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="openrag-ingest",
        description="OpenRAG Composable Ingestion Execution CLI",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Pipeline config file (default: pipeline/presets/ingestion/pipeline.yaml)",
    )
    parser.add_argument("--verbose", action="store_true")

    sub = parser.add_subparsers(dest="command", required=True)

    # submit
    p_submit = sub.add_parser("submit", help="Submit file(s) for ingestion")
    p_submit.add_argument("path", help="File or directory to ingest")
    p_submit.add_argument("--recursive", action="store_true", help="Walk subdirectories")
    p_submit.add_argument(
        "--no-wait",
        action="store_true",
        help="Return immediately with batch_id instead of waiting (Redis only)",
    )

    # status
    p_status = sub.add_parser("status", help="Check batch progress (Redis backend)")
    p_status.add_argument("batch_id", help="Batch ID returned by submit")

    # cancel
    p_cancel = sub.add_parser("cancel", help="Cancel a running batch (Redis backend)")
    p_cancel.add_argument("batch_id", help="Batch ID to cancel")

    # worker
    p_worker = sub.add_parser(
        "worker",
        help="Run as an external Redis queue worker (K8s / worker-mode)",
    )
    p_worker.add_argument(
        "--idle-timeout",
        type=int,
        default=30,
        help="Seconds to wait on empty queue before exiting (default: 30)",
    )

    args = parser.parse_args()

    if args.verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    cmd_map = {
        "submit": _cmd_submit,
        "status": _cmd_status,
        "cancel": _cmd_cancel,
        "worker": _cmd_worker,
    }

    asyncio.run(cmd_map[args.command](args))


if __name__ == "__main__":
    main()
