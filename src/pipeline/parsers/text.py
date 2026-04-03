"""Plain text file parser."""

from __future__ import annotations

import os

from pipeline.types import FileMetadata, ParsedDocument


class PlainTextParser:
    """Read plain-text / markdown files and return as ParsedDocument."""

    async def parse(self, file_path: str, metadata: FileMetadata) -> ParsedDocument:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        return ParsedDocument(
            filename=metadata.filename or os.path.basename(file_path),
            content=content,
            mimetype="text/plain",
            file_path=file_path,
        )
