"""Auto-dispatching parser that selects the best parser by file extension."""

from __future__ import annotations

import logging
import os

from pipeline.types import FileMetadata, ParsedDocument

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

    def _ensure_parsers(self) -> None:
        if self._text is None:
            from pipeline.parsers.text import PlainTextParser
            self._text = PlainTextParser()
        if self._docling is None:
            from pipeline.parsers.docling import DoclingParser
            self._docling = DoclingParser()
        if self._markitdown is None:
            try:
                from pipeline.parsers.markitdown import MarkItDownParser
                self._markitdown = MarkItDownParser()
            except ImportError:
                pass

    async def parse(self, file_path: str, metadata: FileMetadata) -> ParsedDocument:
        self._ensure_parsers()
        ext = os.path.splitext(file_path)[1].lower()

        if ext in _TEXT_EXTENSIONS:
            return await self._text.parse(file_path, metadata)

        if ext in _DOCLING_EXTENSIONS:
            try:
                return await self._docling.parse(file_path, metadata)
            except Exception as e:
                if self._markitdown is not None:
                    logger.warning(
                        "DoclingParser failed, falling back to MarkItDownParser: %s", e
                    )
                    return await self._markitdown.parse(file_path, metadata)
                raise

        if self._markitdown is not None:
            try:
                return await self._markitdown.parse(file_path, metadata)
            except Exception:
                pass

        return await self._docling.parse(file_path, metadata)
