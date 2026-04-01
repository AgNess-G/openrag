"""Semantic chunker using embedding similarity boundaries."""

from __future__ import annotations

from pipeline.types import Chunk, ParsedDocument

try:
    from langchain_experimental.text_splitter import SemanticChunker as _LCSemanticChunker

    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


class SemanticChunker:
    """Split text by semantic similarity boundaries.

    Requires langchain-experimental to be installed.
    Also requires an embeddings object compatible with LangChain's Embeddings interface.
    """

    def __init__(self, embeddings=None) -> None:
        if not _AVAILABLE:
            raise ImportError(
                "langchain-experimental is required for SemanticChunker. "
                "Install with: pip install langchain-experimental"
            )
        if embeddings is None:
            raise ValueError("SemanticChunker requires an embeddings instance")
        self._splitter = _LCSemanticChunker(embeddings=embeddings)

    async def chunk(self, doc: ParsedDocument) -> list[Chunk]:
        if not doc.content:
            return []
        docs = self._splitter.create_documents([doc.content])
        return [
            Chunk(text=d.page_content, index=i, source=doc.filename)
            for i, d in enumerate(docs)
        ]
