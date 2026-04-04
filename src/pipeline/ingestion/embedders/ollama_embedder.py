"""Ollama embedding provider via OpenAI-compatible API."""

from __future__ import annotations

import os

from pipeline.ingestion.embedders.openai_embedder import OpenAIEmbedder


class OllamaEmbedder(OpenAIEmbedder):
    """Generate embeddings via Ollama's OpenAI-compatible endpoint."""

    def __init__(
        self,
        model: str = "nomic-embed-text",
        batch_size: int = 50,
        max_tokens: int = 8000,
    ) -> None:
        base_url = os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434") + "/v1"
        super().__init__(
            model=model,
            batch_size=batch_size,
            max_tokens=max_tokens,
            api_key="ollama",
            base_url=base_url,
        )
