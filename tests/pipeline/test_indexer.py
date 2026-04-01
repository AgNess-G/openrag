"""Tests for the OpenSearch bulk indexer."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from pipeline.indexers.opensearch_bulk import OpenSearchBulkIndexer
from pipeline.types import EmbeddedChunk, FileMetadata


@pytest.fixture
def file_meta():
    return FileMetadata(
        file_path="/tmp/test.txt",
        filename="test.txt",
        file_hash="hash123",
        file_size=100,
        mimetype="text/plain",
        owner_user_id="user1",
    )


@pytest.fixture
def embedded_chunks():
    return [
        EmbeddedChunk(
            text="Hello", index=0, source="test.txt",
            embedding=[0.1] * 384, embedding_model="test-model",
            embedding_dimensions=384,
        ),
        EmbeddedChunk(
            text="World", index=1, source="test.txt",
            embedding=[0.2] * 384, embedding_model="test-model",
            embedding_dimensions=384,
        ),
    ]


@pytest.mark.asyncio
async def test_bulk_indexer_calls_bulk(mock_opensearch_client, file_meta, embedded_chunks):
    mock_opensearch_client.bulk = AsyncMock(return_value={"errors": False, "items": []})

    with patch("utils.embedding_fields.ensure_embedding_field_exists", new_callable=AsyncMock) as mock_ensure:
        mock_ensure.return_value = "chunk_embedding_test_model"
        with patch("utils.embedding_fields.get_embedding_field_name", return_value="chunk_embedding_test_model"):
            with patch("config.settings.get_index_name", return_value="documents"):
                indexer = OpenSearchBulkIndexer(
                    opensearch_client=mock_opensearch_client,
                    bulk_batch_size=500,
                )
                result = await indexer.index(embedded_chunks, file_meta)

    assert result.chunks_indexed == 2
    assert result.document_id == "hash123"
    mock_opensearch_client.bulk.assert_called_once()


@pytest.mark.asyncio
async def test_bulk_indexer_empty_chunks(mock_opensearch_client, file_meta):
    with patch("config.settings.get_index_name", return_value="documents"):
        indexer = OpenSearchBulkIndexer(opensearch_client=mock_opensearch_client)
        result = await indexer.index([], file_meta)

    assert result.status == "skipped"
    assert result.chunks_indexed == 0


@pytest.mark.asyncio
async def test_bulk_indexer_retry_on_failure(mock_opensearch_client, file_meta, embedded_chunks):
    mock_opensearch_client.bulk = AsyncMock(
        side_effect=[Exception("connection error"), {"errors": False, "items": []}]
    )

    with patch("utils.embedding_fields.ensure_embedding_field_exists", new_callable=AsyncMock):
        with patch("utils.embedding_fields.get_embedding_field_name", return_value="chunk_embedding_test_model"):
            with patch("config.settings.get_index_name", return_value="documents"):
                indexer = OpenSearchBulkIndexer(
                    opensearch_client=mock_opensearch_client,
                    retry_attempts=3,
                    retry_backoff=0.01,
                )
                result = await indexer.index(embedded_chunks, file_meta)

    assert result.chunks_indexed == 2
    assert mock_opensearch_client.bulk.call_count == 2
