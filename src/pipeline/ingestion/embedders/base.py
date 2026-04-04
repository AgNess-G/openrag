"""Embedder protocol for the composable pipeline."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pipeline.ingestion.types import Chunk, EmbeddedChunk


@runtime_checkable
class Embedder(Protocol):
    async def embed(self, chunks: list[Chunk]) -> list[EmbeddedChunk]: ...
