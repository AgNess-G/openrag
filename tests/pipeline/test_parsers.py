"""Tests for pipeline parsers."""

from __future__ import annotations

import pytest

from pipeline.parsers.text import PlainTextParser
from pipeline.types import FileMetadata


@pytest.mark.asyncio
async def test_plain_text_parser(sample_text_file, sample_file_metadata):
    parser = PlainTextParser()
    doc = await parser.parse(sample_text_file, sample_file_metadata)
    assert doc.filename == "sample.txt"
    assert len(doc.content) > 0
    assert doc.mimetype == "text/plain"
    assert "Lorem ipsum" in doc.content


@pytest.mark.asyncio
async def test_auto_parser_dispatches_txt(sample_text_file, sample_file_metadata):
    from pipeline.parsers.auto import AutoParser
    from pipeline.parsers.text import PlainTextParser

    text_parser = PlainTextParser()
    auto = AutoParser(text_parser=text_parser, docling_parser=None)
    doc = await auto.parse(sample_text_file, sample_file_metadata)
    assert doc.mimetype == "text/plain"
    assert "Lorem ipsum" in doc.content
