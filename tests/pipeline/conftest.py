"""Shared fixtures for pipeline tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pipeline.types import Chunk, EmbeddedChunk, FileMetadata, ParsedDocument


@pytest.fixture
def mock_opensearch_client():
    client = AsyncMock()
    client.bulk = AsyncMock(return_value={"errors": False, "items": []})
    client.exists = AsyncMock(return_value=False)
    client.indices = AsyncMock()
    client.indices.get_mapping = AsyncMock(return_value={})
    client.indices.put_mapping = AsyncMock()
    return client


@pytest.fixture
def mock_embedding_response():
    def _make(dimensions: int = 384, count: int = 1):
        return [[0.1] * dimensions for _ in range(count)]
    return _make


@pytest.fixture
def sample_text_file(tmp_path):
    path = tmp_path / "sample.txt"
    path.write_text(
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
        "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.\n\n"
        "Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris "
        "nisi ut aliquip ex ea commodo consequat.\n\n"
        "Duis aute irure dolor in reprehenderit in voluptate velit esse "
        "cillum dolore eu fugiat nulla pariatur."
    )
    return str(path)


@pytest.fixture
def sample_file_metadata(sample_text_file):
    return FileMetadata(
        file_path=sample_text_file,
        filename="sample.txt",
        file_hash="abc123",
        file_size=300,
        mimetype="text/plain",
    )


@pytest.fixture
def sample_parsed_doc():
    return ParsedDocument(
        filename="sample.txt",
        content=(
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
            "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.\n\n"
            "Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris."
        ),
        mimetype="text/plain",
    )


@pytest.fixture
def sample_chunks():
    return [
        Chunk(text="Lorem ipsum dolor sit amet.", index=0, source="sample.txt"),
        Chunk(text="Ut enim ad minim veniam.", index=1, source="sample.txt"),
    ]


@pytest.fixture
def sample_embedded_chunks():
    return [
        EmbeddedChunk(
            text="Lorem ipsum dolor sit amet.",
            index=0,
            source="sample.txt",
            embedding=[0.1] * 384,
            embedding_model="test-model",
            embedding_dimensions=384,
        ),
        EmbeddedChunk(
            text="Ut enim ad minim veniam.",
            index=1,
            source="sample.txt",
            embedding=[0.2] * 384,
            embedding_model="test-model",
            embedding_dimensions=384,
        ),
    ]
