"""Tests for pipeline config validation boundaries."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pipeline.config import ChunkerConfig, PipelineConfig


def test_chunk_size_below_minimum():
    with pytest.raises(ValidationError):
        ChunkerConfig(chunk_size=50)


def test_chunk_size_above_maximum():
    with pytest.raises(ValidationError):
        ChunkerConfig(chunk_size=20000)


def test_unknown_parser_type():
    with pytest.raises(ValidationError):
        PipelineConfig.model_validate({"parser": {"type": "nonexistent"}})


def test_unknown_embedder_provider():
    with pytest.raises(ValidationError):
        PipelineConfig.model_validate({"embedder": {"provider": "fake_provider"}})


def test_valid_config_passes():
    config = PipelineConfig.model_validate({
        "version": "1",
        "ingestion_mode": "composable",
        "chunker": {"chunk_size": 500, "chunk_overlap": 100},
    })
    assert config.chunker.chunk_size == 500


def test_negative_chunk_overlap():
    with pytest.raises(ValidationError):
        ChunkerConfig(chunk_overlap=-1)
