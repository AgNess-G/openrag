"""MarkItDown-based document parser (optional dependency)."""

from __future__ import annotations

import os

from pipeline.types import FileMetadata, ParsedDocument

try:
    from markitdown import MarkItDown as _MarkItDown

    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


class MarkItDownParser:
    """Convert documents to Markdown via the markitdown library."""

    def __init__(self) -> None:
        if not _AVAILABLE:
            raise ImportError(
                "markitdown is not installed. "
                "Install it with: pip install 'openrag[markitdown]'"
            )
        self._converter = _MarkItDown()

    async def parse(self, file_path: str, metadata: FileMetadata) -> ParsedDocument:
        result = self._converter.convert(file_path)
        return ParsedDocument(
            filename=metadata.filename or os.path.basename(file_path),
            content=result.text_content,
            mimetype=metadata.mimetype or "text/markdown",
        )

    @staticmethod
    def is_available() -> bool:
        return _AVAILABLE
