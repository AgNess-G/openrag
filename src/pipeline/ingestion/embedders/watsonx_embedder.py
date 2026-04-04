"""IBM watsonx.ai embedding provider."""

from __future__ import annotations

import asyncio
import os

import tiktoken

from pipeline.ingestion.types import Chunk, EmbeddedChunk


class WatsonXEmbedder:
    """Generate embeddings via the IBM watsonx.ai SDK."""

    def __init__(
        self,
        model: str = "ibm/slate-125m-english-rtrvr-v2",
        batch_size: int = 100,
        max_tokens: int = 8000,
        api_key: str | None = None,
        project_id: str | None = None,
        endpoint: str | None = None,
    ) -> None:
        self._model = model
        self._batch_size = batch_size
        self._max_tokens = max_tokens
        self._api_key = api_key or os.getenv("WATSONX_API_KEY", "")
        self._project_id = project_id or os.getenv("WATSONX_PROJECT_ID", "")
        self._endpoint = endpoint or os.getenv(
            "WATSONX_ENDPOINT", "https://us-south.ml.cloud.ibm.com"
        )
        self._client = None

    def _get_client(self):
        if self._client is None:
            from ibm_watsonx_ai import APIClient, Credentials

            creds = Credentials(url=self._endpoint, api_key=self._api_key)
            self._client = APIClient(credentials=creds, project_id=self._project_id)
        return self._client

    async def embed(self, chunks: list[Chunk]) -> list[EmbeddedChunk]:
        if not chunks:
            return []

        batches = self._batch_texts([c.text for c in chunks])
        all_embeddings: list[list[float]] = []

        client = self._get_client()
        for batch in batches:
            result = await asyncio.to_thread(
                client.foundation_models.get_embeddings,
                model_id=self._model,
                input=batch,
            )
            embeddings = result.get("results", [])
            for item in embeddings:
                all_embeddings.append(item.get("embedding", []))

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

    def _batch_texts(self, texts: list[str]) -> list[list[str]]:
        try:
            enc = tiktoken.encoding_for_model(self._model)
        except KeyError:
            enc = tiktoken.get_encoding("cl100k_base")

        batches: list[list[str]] = []
        current: list[str] = []
        current_tokens = 0

        for text in texts:
            tok_count = len(enc.encode(text))
            if (
                current_tokens + tok_count > self._max_tokens
                or len(current) >= self._batch_size
            ):
                if current:
                    batches.append(current)
                current, current_tokens = [], 0
            current.append(text)
            current_tokens += tok_count

        if current:
            batches.append(current)
        return batches
