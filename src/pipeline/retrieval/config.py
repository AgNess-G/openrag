"""Retrieval pipeline configuration models and manager.

Pydantic v2 models for the composable retrieval pipeline.
Loaded from retrieval/presets/retrieval.yaml with env-var overrides.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field


class RetrieverConfig(BaseModel):
    type: Literal["hybrid", "vector", "keyword", "raw"] = "hybrid"
    semantic_weight: float = Field(default=0.7, ge=0.0, le=1.0)
    keyword_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    tie_breaker: float = Field(default=0.0, ge=0.0, le=1.0)
    limit: int = Field(default=10, ge=1, le=200)
    score_threshold: float = Field(default=0.0, ge=0.0)


class CohereRerankerOptions(BaseModel):
    model: str = "rerank-english-v3.0"


class RerankerConfig(BaseModel):
    type: Literal["none", "cohere", "cross_encoder"] = "none"
    top_k: int = Field(default=10, ge=1, le=100)
    cohere: CohereRerankerOptions = Field(default_factory=CohereRerankerOptions)
    cross_encoder_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class AgentConfig(BaseModel):
    type: Literal["openai", "react", "deep"] = "openai"
    provider: str = "openai"
    model: str = "gpt-4o"
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, ge=64)
    system_prompt: str = ""  # falls back to AgentConfig.system_prompt from openrag config if empty
    tools: list[str] = Field(
        default_factory=lambda: [
            "semantic_search",
            "keyword_search",
            "hybrid_search",
            "raw_search",
            "get_document",
            "list_sources",
            "calculator",
        ]
    )
    max_iterations: int = Field(default=10, ge=1, le=50)


class NudgesConfig(BaseModel):
    enabled: bool = True
    type: Literal["langchain", "none"] = "langchain"
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    max_suggestions: int = Field(default=5, ge=1, le=20)
    temperature: float = Field(default=0.5, ge=0.0, le=2.0)


class ConversationConfig(BaseModel):
    rolling_window: int = Field(default=20, ge=1, le=200)


class RetrievalConfig(BaseModel):
    version: str = "1"
    retriever: RetrieverConfig = Field(default_factory=RetrieverConfig)
    reranker: RerankerConfig = Field(default_factory=RerankerConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    nudges: NudgesConfig = Field(default_factory=NudgesConfig)
    conversation: ConversationConfig = Field(default_factory=ConversationConfig)


_ENV_OVERRIDES: dict[str, tuple[str, type]] = {
    "RETRIEVAL_CONFIG_FILE": None,  # handled separately — path override
    "RETRIEVAL_RETRIEVER_TYPE": ("retriever.type", str),
    "RETRIEVAL_RERANKER_TYPE": ("reranker.type", str),
    "RETRIEVAL_AGENT_TYPE": ("agent.type", str),
    "RETRIEVAL_AGENT_MODEL": ("agent.model", str),
    "RETRIEVAL_ROLLING_WINDOW": ("conversation.rolling_window", int),
    "RETRIEVAL_LIMIT": ("retriever.limit", int),
    "RETRIEVAL_SCORE_THRESHOLD": ("retriever.score_threshold", float),
}

_DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "presets" / "retrieval" / "retrieval.yaml"


class RetrievalConfigManager:
    """Loads and manages retrieval configuration from YAML + env overrides."""

    def __init__(self, config_path: str | Path | None = None):
        self._config: RetrievalConfig | None = None
        self._path = Path(
            config_path
            or os.getenv("RETRIEVAL_CONFIG_FILE")
            or str(_DEFAULT_CONFIG)
        )

    def load(self, path: Path | None = None) -> RetrievalConfig:
        target = path or self._path
        if target.exists():
            with open(target) as f:
                raw = yaml.safe_load(f) or {}
        else:
            raw = {}

        self._apply_env_overrides(raw)
        self._config = RetrievalConfig.model_validate(raw)
        return self._config

    def get_config(self) -> RetrievalConfig:
        if self._config is None:
            return self.load()
        return self._config

    def reload(self) -> RetrievalConfig:
        self._config = None
        return self.load()

    @staticmethod
    def _apply_env_overrides(raw: dict[str, Any]) -> None:
        for env_key, mapping in _ENV_OVERRIDES.items():
            if mapping is None:
                continue  # path override handled at __init__
            value = os.getenv(env_key)
            if value is None:
                continue
            dotted_path, cast = mapping
            parts = dotted_path.split(".")
            d = raw
            for part in parts[:-1]:
                d = d.setdefault(part, {})
            d[parts[-1]] = cast(value)
