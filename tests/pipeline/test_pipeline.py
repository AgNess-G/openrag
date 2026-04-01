"""Tests for the pipeline orchestrator and builder."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from pipeline.pipeline import IngestionPipeline
from pipeline.types import (
    Chunk,
    EmbeddedChunk,
    FileMetadata,
    IndexResult,
    ParsedDocument,
)


@pytest.fixture
def mock_stages():
    parser = AsyncMock()
    parser.parse = AsyncMock(return_value=ParsedDocument(
        filename="test.txt", content="Test content", mimetype="text/plain",
    ))

    preprocessor = AsyncMock()
    preprocessor.process = AsyncMock(return_value=ParsedDocument(
        filename="test.txt", content="Test content", mimetype="text/plain",
    ))

    chunker = AsyncMock()
    chunker.chunk = AsyncMock(return_value=[
        Chunk(text="Test", index=0, source="test.txt"),
    ])

    embedder = AsyncMock()
    embedder.embed = AsyncMock(return_value=[
        EmbeddedChunk(
            text="Test", index=0, source="test.txt",
            embedding=[0.1] * 384, embedding_model="test",
            embedding_dimensions=384,
        ),
    ])

    indexer = AsyncMock()
    indexer.index = AsyncMock(return_value=IndexResult(
        document_id="hash123", chunks_indexed=1, index_name="documents",
    ))

    return parser, preprocessor, chunker, embedder, indexer


@pytest.mark.asyncio
async def test_pipeline_run_calls_all_stages(mock_stages):
    parser, preprocessor, chunker, embedder, indexer = mock_stages
    pipeline = IngestionPipeline(
        parser=parser,
        preprocessors=[preprocessor],
        chunker=chunker,
        embedder=embedder,
        indexer=indexer,
    )

    meta = FileMetadata(
        file_path="/tmp/test.txt", filename="test.txt",
        file_hash="hash123", file_size=100, mimetype="text/plain",
    )
    result = await pipeline.run("/tmp/test.txt", meta)

    assert result.status == "success"
    assert result.chunks_indexed == 1
    parser.parse.assert_called_once()
    preprocessor.process.assert_called_once()
    chunker.chunk.assert_called_once()
    embedder.embed.assert_called_once()
    indexer.index.assert_called_once()


@pytest.mark.asyncio
async def test_pipeline_handles_error(mock_stages):
    parser, preprocessor, chunker, embedder, indexer = mock_stages
    parser.parse = AsyncMock(side_effect=RuntimeError("Parse failed"))

    pipeline = IngestionPipeline(
        parser=parser, preprocessors=[], chunker=chunker,
        embedder=embedder, indexer=indexer,
    )
    meta = FileMetadata(
        file_path="/tmp/test.txt", filename="test.txt",
        file_hash="hash123", file_size=100, mimetype="text/plain",
    )
    result = await pipeline.run("/tmp/test.txt", meta)

    assert result.status == "failed"
    assert "Parse failed" in result.error


@pytest.mark.asyncio
async def test_pipeline_empty_chunks(mock_stages):
    parser, preprocessor, chunker, embedder, indexer = mock_stages
    chunker.chunk = AsyncMock(return_value=[])

    pipeline = IngestionPipeline(
        parser=parser, preprocessors=[], chunker=chunker,
        embedder=embedder, indexer=indexer,
    )
    meta = FileMetadata(
        file_path="/tmp/test.txt", filename="test.txt",
        file_hash="hash123", file_size=100, mimetype="text/plain",
    )
    result = await pipeline.run("/tmp/test.txt", meta)

    assert result.status == "skipped"
    embedder.embed.assert_not_called()
