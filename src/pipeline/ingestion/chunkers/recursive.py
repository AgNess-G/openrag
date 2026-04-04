"""Recursive character text splitter chunker."""

from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter

from pipeline.ingestion.types import Chunk, ParsedDocument


class RecursiveChunker:
    """Split text using recursive character boundaries."""

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        separators: list[str] | None = None,
    ) -> None:
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=separators or ["\n\n", "\n", " ", ""],
        )

    async def chunk(self, doc: ParsedDocument) -> list[Chunk]:
        if not doc.content:
            return []
        texts = self._splitter.split_text(doc.content)
        return [
            Chunk(text=t, index=i, source=doc.filename)
            for i, t in enumerate(texts)
        ]
