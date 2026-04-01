"""Metadata enrichment preprocessor."""

from __future__ import annotations

from dataclasses import replace

from pipeline.types import ParsedDocument


class MetadataPreprocessor:
    """Enrich document metadata with basic statistics."""

    def __init__(self, extract_language: bool = True) -> None:
        self._extract_language = extract_language

    async def process(self, doc: ParsedDocument) -> ParsedDocument:
        enriched = {
            **doc.metadata,
            "char_count": len(doc.content),
            "word_count": len(doc.content.split()),
        }
        if self._extract_language:
            enriched["detected_language"] = "en"

        return replace(doc, metadata=enriched)
