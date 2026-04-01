"""Tests for pipeline embedders."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pipeline.embedders.openai_embedder import OpenAIEmbedder
from pipeline.types import Chunk


@pytest.mark.asyncio
async def test_openai_embedder_returns_embedded_chunks():
    embedder = OpenAIEmbedder(model="text-embedding-3-small", api_key="test-key")

    mock_embedding = MagicMock()
    mock_embedding.embedding = [0.1] * 1536

    mock_response = MagicMock()
    mock_response.data = [mock_embedding, mock_embedding]

    with patch.object(embedder._client.embeddings, "create", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = mock_response

        chunks = [
            Chunk(text="Hello world", index=0, source="test.txt"),
            Chunk(text="Goodbye world", index=1, source="test.txt"),
        ]
        result = await embedder.embed(chunks)

    assert len(result) == 2
    assert result[0].embedding_model == "text-embedding-3-small"
    assert result[0].embedding_dimensions == 1536
    assert len(result[0].embedding) == 1536


@pytest.mark.asyncio
async def test_openai_embedder_empty_input():
    embedder = OpenAIEmbedder(model="text-embedding-3-small", api_key="test-key")
    result = await embedder.embed([])
    assert result == []


def test_batching_splits_large_input():
    embedder = OpenAIEmbedder(
        model="text-embedding-3-small",
        batch_size=2,
        max_tokens=100,
        api_key="test-key",
    )
    texts = ["short text"] * 5
    batches = embedder._batch_by_tokens(texts)
    assert len(batches) >= 2
    for batch in batches:
        assert len(batch) <= 2
