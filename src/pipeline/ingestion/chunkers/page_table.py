"""Page/table-aware chunker for structured Docling output."""

from __future__ import annotations

from pipeline.ingestion.types import Chunk, ParsedDocument


class PageTableChunker:
    """Create chunks from docling-structured pages and tables.

    Falls back to paragraph splitting when structured data is absent.
    """

    async def chunk(self, doc: ParsedDocument) -> list[Chunk]:
        chunks: list[Chunk] = []
        idx = 0

        if doc.pages:
            for page_data in doc.pages:
                text = page_data.get("text", "")
                if text.strip():
                    chunks.append(Chunk(
                        text=text,
                        index=idx,
                        source=doc.filename,
                        page=page_data.get("page"),
                        chunk_type="text",
                    ))
                    idx += 1

        if doc.tables:
            for table_data in doc.tables:
                text = table_data.get("text", "")
                if text.strip():
                    chunks.append(Chunk(
                        text=text,
                        index=idx,
                        source=doc.filename,
                        page=table_data.get("page"),
                        chunk_type="table",
                    ))
                    idx += 1

        if not chunks:
            chunks = self._fallback_split(doc, idx)

        return chunks

    @staticmethod
    def _fallback_split(doc: ParsedDocument, start_idx: int = 0) -> list[Chunk]:
        """Simple paragraph splitting for unstructured content."""
        paragraphs = [p.strip() for p in doc.content.split("\n\n") if p.strip()]
        if not paragraphs:
            return []
        return [
            Chunk(text=p, index=start_idx + i, source=doc.filename)
            for i, p in enumerate(paragraphs)
        ]
