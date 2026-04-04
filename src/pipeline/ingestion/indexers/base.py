"""Indexer protocol for the composable pipeline."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pipeline.ingestion.types import EmbeddedChunk, FileMetadata, IndexResult


@runtime_checkable
class Indexer(Protocol):
    async def index(self, chunks: list[EmbeddedChunk], metadata: FileMetadata) -> IndexResult: ...
