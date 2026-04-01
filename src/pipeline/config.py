"""Pipeline configuration models and manager.

Pydantic v2 models for the composable ingestion pipeline configuration.
Loaded from config/pipeline.yaml at boot time with env-var overrides.
"""

from __future__ import annotations

import json
import os
from enum import Enum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class ParserType(str, Enum):
    auto = "auto"
    docling = "docling"
    markitdown = "markitdown"
    text = "text"


class ChunkerType(str, Enum):
    recursive = "recursive"
    character = "character"
    semantic = "semantic"
    page_table = "page_table"
    docling_hybrid = "docling_hybrid"


class DoclingOptions(BaseModel):
    ocr: bool = False
    ocr_engine: Literal["easyocr", "tesseract"] = "easyocr"
    table_structure: bool = True
    picture_descriptions: bool = False


class MarkItDownOptions(BaseModel):
    model_config = {"extra": "allow"}


class ParserConfig(BaseModel):
    type: ParserType = ParserType.auto
    docling: DoclingOptions = Field(default_factory=DoclingOptions)
    markitdown: MarkItDownOptions = Field(default_factory=MarkItDownOptions)


class PreprocessorConfig(BaseModel):
    model_config = {"extra": "allow"}
    type: str


class ChunkerConfig(BaseModel):
    type: ChunkerType = ChunkerType.recursive
    chunk_size: int = Field(default=1000, ge=100, le=10000)
    chunk_overlap: int = Field(default=200, ge=0, le=5000)
    separators: list[str] = Field(
        default_factory=lambda: ["\n\n", "\n", " "]
    )


class EmbedderConfig(BaseModel):
    provider: Literal["openai", "watsonx", "ollama", "huggingface"] = "openai"
    model: str = "text-embedding-3-small"
    batch_size: int = Field(default=100, ge=1, le=2000)
    max_tokens: int = Field(default=8000, ge=100)


class IndexerConfig(BaseModel):
    type: str = "opensearch_bulk"
    bulk_batch_size: int = Field(default=500, ge=1, le=5000)
    retry_attempts: int = Field(default=3, ge=0, le=10)
    retry_backoff: float = Field(default=2.0, ge=0.1, le=30.0)


class RayConfig(BaseModel):
    address: str = "auto"
    num_cpus_per_task: int = Field(default=1, ge=1)
    num_gpus_per_task: int = Field(default=0, ge=0)
    max_retries: int = Field(default=3, ge=0)


class ExecutionConfig(BaseModel):
    backend: Literal["local", "ray"] = "local"
    concurrency: int = Field(default=4, ge=1, le=64)
    timeout: int = Field(default=3600, ge=60)
    ray: RayConfig = Field(default_factory=RayConfig)


class PipelineConfig(BaseModel):
    version: str = "1"
    ingestion_mode: Literal["langflow", "traditional", "composable"] = "langflow"
    parser: ParserConfig = Field(default_factory=ParserConfig)
    preprocessors: list[PreprocessorConfig] = Field(default_factory=list)
    chunker: ChunkerConfig = Field(default_factory=ChunkerConfig)
    embedder: EmbedderConfig = Field(default_factory=EmbedderConfig)
    indexer: IndexerConfig = Field(default_factory=IndexerConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)

    @model_validator(mode="before")
    @classmethod
    def coerce_preprocessors(cls, data: Any) -> Any:
        """Allow preprocessors to be specified as plain dicts in YAML."""
        if isinstance(data, dict) and "preprocessors" in data:
            pps = data["preprocessors"]
            if isinstance(pps, list):
                data["preprocessors"] = [
                    p if isinstance(p, PreprocessorConfig) else PreprocessorConfig(**p)
                    for p in pps
                    if isinstance(p, (dict, PreprocessorConfig))
                ]
        return data


_ENV_OVERRIDES: dict[str, tuple[str, type]] = {
    "PIPELINE_INGESTION_MODE": ("ingestion_mode", str),
    "PIPELINE_PARSER_TYPE": ("parser.type", str),
    "PIPELINE_CHUNKER": ("chunker.type", str),
    "PIPELINE_CHUNK_SIZE": ("chunker.chunk_size", int),
    "PIPELINE_CHUNK_OVERLAP": ("chunker.chunk_overlap", int),
    "PIPELINE_EMBEDDER_PROVIDER": ("embedder.provider", str),
    "PIPELINE_EMBEDDER_MODEL": ("embedder.model", str),
    "PIPELINE_EXECUTION_BACKEND": ("execution.backend", str),
    "PIPELINE_EXECUTION_CONCURRENCY": ("execution.concurrency", int),
    "PIPELINE_EXECUTION_TIMEOUT": ("execution.timeout", int),
    "RAY_ADDRESS": ("execution.ray.address", str),
}


class PipelineConfigManager:
    """Loads and manages pipeline configuration from YAML + env overrides."""

    def __init__(self, config_path: str | Path | None = None):
        self._config: PipelineConfig | None = None
        self._path = Path(
            config_path
            or os.getenv("PIPELINE_CONFIG_FILE", "config/pipeline.yaml")
        )

    def load(self, path: Path | None = None) -> PipelineConfig:
        target = path or self._path
        if target.exists():
            with open(target) as f:
                raw = yaml.safe_load(f) or {}
        else:
            raw = {}

        self._apply_env_overrides(raw)
        self._config = PipelineConfig.model_validate(raw)
        return self._config

    def get_config(self) -> PipelineConfig:
        if self._config is None:
            return self.load()
        return self._config

    def reload(self) -> PipelineConfig:
        self._config = None
        return self.load()

    @staticmethod
    def _apply_env_overrides(raw: dict[str, Any]) -> None:
        for env_key, (dotted_path, cast) in _ENV_OVERRIDES.items():
            value = os.getenv(env_key)
            if value is None:
                continue
            parts = dotted_path.split(".")
            d = raw
            for part in parts[:-1]:
                d = d.setdefault(part, {})
            d[parts[-1]] = cast(value)
