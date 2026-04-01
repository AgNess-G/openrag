"""DocumentParser protocol for the composable pipeline."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pipeline.types import FileMetadata, ParsedDocument


@runtime_checkable
class DocumentParser(Protocol):
    async def parse(self, file_path: str, metadata: FileMetadata) -> ParsedDocument: ...
