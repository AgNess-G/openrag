"""Preprocessor protocol for the composable pipeline."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pipeline.ingestion.types import ParsedDocument


@runtime_checkable
class Preprocessor(Protocol):
    async def process(self, doc: ParsedDocument) -> ParsedDocument: ...
