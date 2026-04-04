"""Auto-dispatching parser that selects the best parser by file extension."""

from __future__ import annotations

import logging
import os

from pipeline.ingestion.types import FileMetadata, ParsedDocument

logger = logging.getLogger(__name__)

_DOCLING_EXTENSIONS = frozenset({
    ".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm",
    ".xls", ".doc", ".ppt", ".rtf",
})
_TEXT_EXTENSIONS = frozenset({".txt", ".md", ".rst", ".csv", ".tsv", ".log"})


class AutoParser:
    """Automatically dispatch to the best parser based on file extension."""

    def __init__(
        self,
        docling_parser=None,
        text_parser=None,
        markitdown_parser=None,
    ) -> None:
        self._docling = docling_parser
        self._text = text_parser
        self._markitdown = markitdown_parser
        self.last_used: str | None = None  # set after each parse() call

    def _ensure_parsers(self) -> None:
        if self._text is None:
            from pipeline.ingestion.parsers.text import PlainTextParser
            self._text = PlainTextParser()
        if self._docling is None:
            from pipeline.ingestion.parsers.docling import DoclingParser
            self._docling = DoclingParser()
        if self._markitdown is None:
            try:
                from pipeline.ingestion.parsers.markitdown import MarkItDownParser
                self._markitdown = MarkItDownParser()
            except ImportError:
                pass

    async def parse(self, file_path: str, metadata: FileMetadata) -> ParsedDocument:
        self._ensure_parsers()
        ext = os.path.splitext(file_path)[1].lower()

        if ext in _TEXT_EXTENSIONS:
            self.last_used = type(self._text).__name__
            return await self._text.parse(file_path, metadata)

        if ext in _DOCLING_EXTENSIONS:
            try:
                result = await self._docling.parse(file_path, metadata)
                self.last_used = type(self._docling).__name__
                return result
            except Exception as e:
                if self._markitdown is not None:
                    logger.warning(
                        "DoclingParser failed, falling back to MarkItDownParser: %s", e
                    )
                    result = await self._markitdown.parse(file_path, metadata)
                    self.last_used = f"MarkItDownParser (fallback from DoclingParser: {e})"
                    return result
                raise

        if self._markitdown is not None:
            try:
                result = await self._markitdown.parse(file_path, metadata)
                self.last_used = type(self._markitdown).__name__
                return result
            except Exception:
                pass

        self.last_used = type(self._docling).__name__
        return await self._docling.parse(file_path, metadata)
