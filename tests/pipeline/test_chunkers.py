"""Tests for pipeline chunkers."""

from __future__ import annotations

import pytest

from pipeline.chunkers.recursive import RecursiveChunker
from pipeline.types import ParsedDocument


@pytest.mark.asyncio
async def test_recursive_chunker_splits():
    content = ("A" * 500 + "\n\n") * 5
    doc = ParsedDocument(filename="test.txt", content=content, mimetype="text/plain")
    chunker = RecursiveChunker(chunk_size=600, chunk_overlap=50)
    chunks = await chunker.chunk(doc)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c.text) <= 600 + 50
        assert c.source == "test.txt"


@pytest.mark.asyncio
async def test_chunk_size_respected():
    content = "word " * 1000
    doc = ParsedDocument(filename="test.txt", content=content, mimetype="text/plain")
    chunker = RecursiveChunker(chunk_size=200, chunk_overlap=20)
    chunks = await chunker.chunk(doc)
    for c in chunks:
        assert len(c.text) <= 200 + 50


@pytest.mark.asyncio
async def test_empty_input():
    doc = ParsedDocument(filename="empty.txt", content="", mimetype="text/plain")
    chunker = RecursiveChunker()
    chunks = await chunker.chunk(doc)
    assert chunks == []


@pytest.mark.asyncio
async def test_chunk_indices():
    content = ("Paragraph one.\n\n" + "Paragraph two.\n\n") * 10
    doc = ParsedDocument(filename="test.txt", content=content, mimetype="text/plain")
    chunker = RecursiveChunker(chunk_size=100, chunk_overlap=10)
    chunks = await chunker.chunk(doc)
    indices = [c.index for c in chunks]
    assert indices == list(range(len(chunks)))
