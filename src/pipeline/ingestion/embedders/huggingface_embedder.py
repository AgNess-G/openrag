"""Local HuggingFace sentence-transformers embedding provider."""

from __future__ import annotations

import asyncio

from pipeline.ingestion.types import Chunk, EmbeddedChunk

try:
    from sentence_transformers import SentenceTransformer

    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


class HuggingFaceEmbedder:
    """Generate embeddings locally using sentence-transformers."""

    def __init__(
        self,
        model: str = "all-MiniLM-L6-v2",
        batch_size: int = 64,
    ) -> None:
        if not _AVAILABLE:
            raise ImportError(
                "sentence-transformers is not installed. "
                "Install with: pip install 'openrag[huggingface]'"
            )
        self._model_name = model
        self._batch_size = batch_size
        self._model = SentenceTransformer(model)

    async def embed(self, chunks: list[Chunk]) -> list[EmbeddedChunk]:
        if not chunks:
            return []

        texts = [c.text for c in chunks]
        embeddings = await asyncio.to_thread(
            self._model.encode,
            texts,
            batch_size=self._batch_size,
            show_progress_bar=False,
        )

        dims = embeddings.shape[1] if hasattr(embeddings, "shape") else len(embeddings[0])
        return [
            EmbeddedChunk(
                text=c.text,
                index=c.index,
                page=c.page,
                chunk_type=c.chunk_type,
                source=c.source,
                embedding=emb.tolist() if hasattr(emb, "tolist") else list(emb),
                embedding_model=self._model_name,
                embedding_dimensions=dims,
                metadata=c.metadata,
            )
            for c, emb in zip(chunks, embeddings)
        ]

    @staticmethod
    def is_available() -> bool:
        return _AVAILABLE
