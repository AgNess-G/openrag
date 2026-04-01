"""OpenAI embedding provider."""

from __future__ import annotations

import os
from typing import Sequence

import tiktoken
from openai import AsyncOpenAI

from pipeline.types import Chunk, EmbeddedChunk


class OpenAIEmbedder:
    """Generate embeddings via the OpenAI API."""

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        batch_size: int = 100,
        max_tokens: int = 8000,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._model = model
        self._batch_size = batch_size
        self._max_tokens = max_tokens
        self._client = AsyncOpenAI(
            api_key=api_key or os.getenv("OPENAI_API_KEY"),
            base_url=base_url,
        )

    async def embed(self, chunks: list[Chunk]) -> list[EmbeddedChunk]:
        if not chunks:
            return []

        batches = self._batch_by_tokens([c.text for c in chunks])
        all_embeddings: list[list[float]] = []

        for batch in batches:
            resp = await self._client.embeddings.create(
                model=self._model,
                input=batch,
            )
            all_embeddings.extend(d.embedding for d in resp.data)

        dims = len(all_embeddings[0]) if all_embeddings else 0
        return [
            EmbeddedChunk(
                text=c.text,
                index=c.index,
                page=c.page,
                chunk_type=c.chunk_type,
                source=c.source,
                embedding=emb,
                embedding_model=self._model,
                embedding_dimensions=dims,
                metadata=c.metadata,
            )
            for c, emb in zip(chunks, all_embeddings)
        ]

    def _batch_by_tokens(self, texts: Sequence[str]) -> list[list[str]]:
        try:
            enc = tiktoken.encoding_for_model(self._model)
        except KeyError:
            enc = tiktoken.get_encoding("cl100k_base")

        batches: list[list[str]] = []
        current: list[str] = []
        current_tokens = 0

        for text in texts:
            tok_count = len(enc.encode(text))

            if tok_count > self._max_tokens:
                if current:
                    batches.append(current)
                    current, current_tokens = [], 0
                tokens = enc.encode(text)
                for i in range(0, len(tokens), self._max_tokens):
                    batches.append([enc.decode(tokens[i : i + self._max_tokens])])
                continue

            if (
                current_tokens + tok_count > self._max_tokens
                or len(current) >= self._batch_size
            ):
                batches.append(current)
                current, current_tokens = [], 0

            current.append(text)
            current_tokens += tok_count

        if current:
            batches.append(current)

        return batches
