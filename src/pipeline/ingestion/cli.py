"""CLI for the composable ingestion pipeline.

Usage:
    python -m pipeline.cli run <path> [--config pipeline/presets/pipeline.yaml] [--dry-run] [--recursive]
    python -m pipeline.cli parse <file>
    python -m pipeline.cli chunk <file>
    python -m pipeline.cli embed <file>
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import sys


def _file_metadata(file_path: str):
    from pipeline.ingestion.types import FileMetadata

    stat = os.stat(file_path)
    with open(file_path, "rb") as f:
        file_hash = hashlib.sha256(f.read()).hexdigest()

    import mimetypes
    mt, _ = mimetypes.guess_type(file_path)

    return FileMetadata(
        file_path=os.path.abspath(file_path),
        filename=os.path.basename(file_path),
        file_hash=file_hash,
        file_size=stat.st_size,
        mimetype=mt or "application/octet-stream",
    )


async def _cmd_run(args: argparse.Namespace) -> None:
    from pipeline.ingestion.config import PipelineConfigManager
    from pipeline.ingestion.execution.local_backend import LocalBackend
    from pipeline.ingestion.pipeline import PipelineBuilder
    from pipeline.ingestion.registry import get_default_registry

    mgr = PipelineConfigManager(args.config)
    config = mgr.load()
    config.ingestion_mode = "composable"

    registry = get_default_registry()
    builder = PipelineBuilder(config, registry)
    pipeline = builder.build()

    paths: list[str] = []
    if os.path.isdir(args.path):
        for root, _, files in os.walk(args.path):
            paths.extend(os.path.join(root, f) for f in files)
            if not args.recursive:
                break
    else:
        paths.append(args.path)

    if not paths:
        print("No files found.")
        return

    metas = [_file_metadata(p) for p in paths]

    if args.dry_run:
        for fm in metas:
            doc = await pipeline.parser.parse(fm.file_path, fm)
            for pp in pipeline.preprocessors:
                doc = await pp.process(doc)
            chunks = await pipeline.chunker.chunk(doc)
            print(f"{fm.filename}: {len(chunks)} chunks (dry-run, not embedded/indexed)")
        return

    backend = LocalBackend(concurrency=config.execution.concurrency)
    batch_id = await backend.submit(pipeline, metas)

    await asyncio.gather(*backend._batches[batch_id].tasks, return_exceptions=True)
    progress = await backend.get_progress(batch_id)

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


async def _cmd_parse(args: argparse.Namespace) -> None:
    from pipeline.ingestion.config import PipelineConfigManager
    from pipeline.ingestion.pipeline import PipelineBuilder
    from pipeline.ingestion.registry import get_default_registry

    mgr = PipelineConfigManager(args.config)
    config = mgr.load()
    registry = get_default_registry()
    builder = PipelineBuilder(config, registry)
    pipeline = builder.build()

    fm = _file_metadata(args.file)
    doc = await pipeline.parser.parse(fm.file_path, fm)
    print(f"Filename:   {doc.filename}")
    print(f"Content:    {len(doc.content)} chars")
    print(f"Pages:      {len(doc.pages) if doc.pages else 0}")
    print(f"Tables:     {len(doc.tables) if doc.tables else 0}")
    print(f"Mimetype:   {doc.mimetype}")


async def _cmd_chunk(args: argparse.Namespace) -> None:
    from pipeline.ingestion.config import PipelineConfigManager
    from pipeline.ingestion.pipeline import PipelineBuilder
    from pipeline.ingestion.registry import get_default_registry

    mgr = PipelineConfigManager(args.config)
    config = mgr.load()
    registry = get_default_registry()
    builder = PipelineBuilder(config, registry)
    pipeline = builder.build()

    fm = _file_metadata(args.file)
    doc = await pipeline.parser.parse(fm.file_path, fm)
    for pp in pipeline.preprocessors:
        doc = await pp.process(doc)
    chunks = await pipeline.chunker.chunk(doc)

    for c in chunks:
        preview = c.text[:100].replace("\n", " ")
        print(f"[{c.index:3d}] ({c.chunk_type:5s}) p={c.page} | {preview}...")


async def _cmd_embed(args: argparse.Namespace) -> None:
    from pipeline.ingestion.config import PipelineConfigManager
    from pipeline.ingestion.pipeline import PipelineBuilder
    from pipeline.ingestion.registry import get_default_registry

    mgr = PipelineConfigManager(args.config)
    config = mgr.load()
    registry = get_default_registry()
    builder = PipelineBuilder(config, registry)
    pipeline = builder.build()

    fm = _file_metadata(args.file)
    doc = await pipeline.parser.parse(fm.file_path, fm)
    for pp in pipeline.preprocessors:
        doc = await pp.process(doc)
    chunks = await pipeline.chunker.chunk(doc)
    embedded = await pipeline.embedder.embed(chunks)

    for ec in embedded:
        preview = ec.text[:80].replace("\n", " ")
        print(
            f"[{ec.index:3d}] dims={ec.embedding_dimensions} "
            f"model={ec.embedding_model} | {preview}..."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pipeline", description="OpenRAG Composable Ingestion Pipeline CLI"
    )
    parser.add_argument(
        "--config", default=None, help="Pipeline config file path (default: pipeline/presets/pipeline.yaml)"
    )
    parser.add_argument("--verbose", action="store_true")

    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Run full pipeline on file(s)")
    p_run.add_argument("path", help="File or directory path")
    p_run.add_argument("--recursive", action="store_true", help="Walk subdirectories")
    p_run.add_argument("--dry-run", action="store_true", help="Parse+chunk only")

    p_parse = sub.add_parser("parse", help="Parse a single file")
    p_parse.add_argument("file", help="File path")

    p_chunk = sub.add_parser("chunk", help="Parse + chunk a single file")
    p_chunk.add_argument("file", help="File path")

    p_embed = sub.add_parser("embed", help="Parse + chunk + embed a single file")
    p_embed.add_argument("file", help="File path")

    args = parser.parse_args()

    if args.verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    cmd_map = {
        "run": _cmd_run,
        "parse": _cmd_parse,
        "chunk": _cmd_chunk,
        "embed": _cmd_embed,
    }

    asyncio.run(cmd_map[args.command](args))


if __name__ == "__main__":
    main()
