"""Ingestion registry for the composable ingestion pipeline.

Maps (stage_type, name) -> component class/factory for dynamic lookup.
"""

from __future__ import annotations

from typing import Any

VALID_STAGE_TYPES = frozenset({"parser", "preprocessor", "chunker", "embedder", "indexer"})


class IngestionRegistry:
    def __init__(self) -> None:
        self._components: dict[tuple[str, str], Any] = {}

    def register(self, name: str, stage_type: str, cls_or_factory: Any) -> None:
        if stage_type not in VALID_STAGE_TYPES:
            raise ValueError(
                f"Invalid stage_type '{stage_type}'. Must be one of: {sorted(VALID_STAGE_TYPES)}"
            )
        self._components[(stage_type, name)] = cls_or_factory

    def get(self, name: str, stage_type: str) -> Any:
        key = (stage_type, name)
        if key not in self._components:
            available = self.list_components(stage_type)
            raise KeyError(
                f"No {stage_type} registered with name '{name}'. "
                f"Available: {available}"
            )
        return self._components[key]

    def list_components(self, stage_type: str) -> list[str]:
        return [name for (st, name) in self._components if st == stage_type]

    def has(self, name: str, stage_type: str) -> bool:
        return (stage_type, name) in self._components


_default_registry: IngestionRegistry | None = None


def get_default_registry() -> IngestionRegistry:
    """Return the singleton default registry, populating it on first call."""
    global _default_registry
    if _default_registry is None:
        _default_registry = IngestionRegistry()
        _populate_defaults(_default_registry)
    return _default_registry


def _populate_defaults(registry: IngestionRegistry) -> None:
    """Register all built-in components. Imports are deferred to avoid circular deps."""
    from pipeline.ingestion.parsers.auto import AutoParser
    from pipeline.ingestion.parsers.docling import DoclingParser
    from pipeline.ingestion.parsers.markitdown import MarkItDownParser
    from pipeline.ingestion.parsers.text import PlainTextParser

    registry.register("auto", "parser", AutoParser)
    registry.register("docling", "parser", DoclingParser)
    registry.register("markitdown", "parser", MarkItDownParser)
    registry.register("text", "parser", PlainTextParser)

    from pipeline.ingestion.preprocessors.cleaning import CleaningPreprocessor
    from pipeline.ingestion.preprocessors.dedup import DedupPreprocessor
    from pipeline.ingestion.preprocessors.metadata import MetadataPreprocessor

    registry.register("cleaning", "preprocessor", CleaningPreprocessor)
    registry.register("dedup", "preprocessor", DedupPreprocessor)
    registry.register("metadata", "preprocessor", MetadataPreprocessor)

    from pipeline.ingestion.chunkers.character import CharacterChunker
    from pipeline.ingestion.chunkers.docling_hybrid import DoclingHybridChunker
    from pipeline.ingestion.chunkers.page_table import PageTableChunker
    from pipeline.ingestion.chunkers.recursive import RecursiveChunker
    from pipeline.ingestion.chunkers.semantic import SemanticChunker

    registry.register("recursive", "chunker", RecursiveChunker)
    registry.register("character", "chunker", CharacterChunker)
    registry.register("semantic", "chunker", SemanticChunker)
    registry.register("page_table", "chunker", PageTableChunker)
    registry.register("docling_hybrid", "chunker", DoclingHybridChunker)

    from pipeline.ingestion.embedders.huggingface_embedder import HuggingFaceEmbedder
    from pipeline.ingestion.embedders.ollama_embedder import OllamaEmbedder
    from pipeline.ingestion.embedders.openai_embedder import OpenAIEmbedder
    from pipeline.ingestion.embedders.watsonx_embedder import WatsonXEmbedder

    registry.register("openai", "embedder", OpenAIEmbedder)
    registry.register("ollama", "embedder", OllamaEmbedder)
    registry.register("watsonx", "embedder", WatsonXEmbedder)
    registry.register("huggingface", "embedder", HuggingFaceEmbedder)

    from pipeline.ingestion.indexers.opensearch_bulk import OpenSearchBulkIndexer

    registry.register("opensearch_bulk", "indexer", OpenSearchBulkIndexer)
