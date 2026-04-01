"""Character-based text splitter chunker."""

from __future__ import annotations

from langchain_text_splitters import CharacterTextSplitter

from pipeline.types import Chunk, ParsedDocument


class CharacterChunker:
    """Split text on a single separator character."""

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        separator: str = "\n\n",
    ) -> None:
        self._splitter = CharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separator=separator,
        )

    async def chunk(self, doc: ParsedDocument) -> list[Chunk]:
        if not doc.content:
            return []
        texts = self._splitter.split_text(doc.content)
        return [
            Chunk(text=t, index=i, source=doc.filename)
            for i, t in enumerate(texts)
        ]
