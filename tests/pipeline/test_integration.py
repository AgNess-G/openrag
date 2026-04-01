"""Integration tests for the pipeline (requires running services).

These tests are marked slow and require a running OpenSearch instance.
Run with: pytest -m slow tests/pipeline/test_integration.py
"""

from __future__ import annotations

import pytest

from pipeline.chunkers.recursive import RecursiveChunker
from pipeline.parsers.text import PlainTextParser
from pipeline.pipeline import IngestionPipeline
from pipeline.types import FileMetadata


@pytest.mark.slow
@pytest.mark.asyncio
async def test_full_pipeline_text_to_chunks(sample_text_file, sample_file_metadata):
    """Test parse + chunk flow end-to-end without embedding/indexing."""
    parser = PlainTextParser()
    chunker = RecursiveChunker(chunk_size=200, chunk_overlap=20)

    doc = await parser.parse(sample_text_file, sample_file_metadata)
    assert doc.content
    assert doc.filename == "sample.txt"

    chunks = await chunker.chunk(doc)
    assert len(chunks) >= 1
    for c in chunks:
        assert len(c.text) > 0
        assert c.source == "sample.txt"
