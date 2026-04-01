"""Tests for pipeline configuration loading and validation."""

from __future__ import annotations

import pytest

from pipeline.config import PipelineConfig, PipelineConfigManager


def test_defaults():
    config = PipelineConfig()
    assert config.version == "1"
    assert config.ingestion_mode == "langflow"
    assert config.parser.type.value == "auto"
    assert config.chunker.chunk_size == 1000
    assert config.chunker.chunk_overlap == 200
    assert config.embedder.provider == "openai"
    assert config.execution.backend == "local"
    assert config.execution.concurrency == 4


def test_yaml_loading(tmp_path):
    cfg_file = tmp_path / "pipeline.yaml"
    cfg_file.write_text(
        "version: '1'\n"
        "ingestion_mode: composable\n"
        "chunker:\n"
        "  chunk_size: 500\n"
        "  chunk_overlap: 100\n"
    )
    mgr = PipelineConfigManager(cfg_file)
    config = mgr.load()
    assert config.ingestion_mode == "composable"
    assert config.chunker.chunk_size == 500
    assert config.chunker.chunk_overlap == 100


def test_env_override(monkeypatch, tmp_path):
    cfg_file = tmp_path / "pipeline.yaml"
    cfg_file.write_text("version: '1'\n")
    monkeypatch.setenv("PIPELINE_EXECUTION_BACKEND", "ray")
    mgr = PipelineConfigManager(cfg_file)
    config = mgr.load()
    assert config.execution.backend == "ray"


def test_missing_file_uses_defaults():
    mgr = PipelineConfigManager("/nonexistent/pipeline.yaml")
    config = mgr.load()
    assert config.ingestion_mode == "langflow"


def test_preset_loading(tmp_path):
    preset = tmp_path / "composable-basic.yaml"
    preset.write_text(
        "version: '1'\n"
        "ingestion_mode: composable\n"
        "parser:\n"
        "  type: auto\n"
        "chunker:\n"
        "  type: recursive\n"
        "  chunk_size: 1000\n"
        "embedder:\n"
        "  provider: openai\n"
    )
    mgr = PipelineConfigManager(preset)
    config = mgr.load()
    assert config.ingestion_mode == "composable"
    assert config.parser.type.value == "auto"
