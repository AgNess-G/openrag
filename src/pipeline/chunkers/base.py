"""Chunker protocol for the composable pipeline."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pipeline.types import Chunk, ParsedDocument


@runtime_checkable
class Chunker(Protocol):
    async def chunk(self, doc: ParsedDocument) -> list[Chunk]: ...
