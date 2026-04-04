"""Component registry for the composable retrieval pipeline.

Maps (stage_type, name) -> component class/factory for dynamic lookup.
"""

from __future__ import annotations

from typing import Any

VALID_STAGE_TYPES = frozenset({"retriever", "reranker", "agent", "tool", "nudges"})


class RetrievalRegistry:
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


_default_registry: RetrievalRegistry | None = None


def get_default_registry() -> RetrievalRegistry:
    """Return the singleton default registry, populating it on first call."""
    global _default_registry
    if _default_registry is None:
        _default_registry = RetrievalRegistry()
        _populate_defaults(_default_registry)
    return _default_registry


def _populate_defaults(registry: RetrievalRegistry) -> None:
    """Register all built-in components. Imports deferred to avoid circular deps."""
    from pipeline.retrieval.retrievers.opensearch_hybrid import HybridRetriever
    from pipeline.retrieval.retrievers.opensearch_vector import VectorRetriever
    from pipeline.retrieval.retrievers.opensearch_keyword import KeywordRetriever
    from pipeline.retrieval.retrievers.opensearch_raw import RawRetriever

    registry.register("hybrid", "retriever", HybridRetriever)
    registry.register("vector", "retriever", VectorRetriever)
    registry.register("keyword", "retriever", KeywordRetriever)
    registry.register("raw", "retriever", RawRetriever)

    from pipeline.retrieval.rerankers.none import PassthroughReranker
    from pipeline.retrieval.rerankers.cohere import CohereReranker
    from pipeline.retrieval.rerankers.cross_encoder import CrossEncoderReranker

    registry.register("none", "reranker", PassthroughReranker)
    registry.register("cohere", "reranker", CohereReranker)
    registry.register("cross_encoder", "reranker", CrossEncoderReranker)

    from pipeline.retrieval.agents.openai_agent import OpenAIAgent
    from pipeline.retrieval.agents.react_agent import ReActAgent
    from pipeline.retrieval.agents.deep_agent import DeepAgent

    registry.register("openai", "agent", OpenAIAgent)
    registry.register("react", "agent", ReActAgent)
    registry.register("deep", "agent", DeepAgent)

    from pipeline.retrieval.nudges.langchain_nudges import LangChainNudgesGenerator
    from pipeline.retrieval.nudges.none import PassthroughNudgesGenerator

    registry.register("langchain", "nudges", LangChainNudgesGenerator)
    registry.register("none", "nudges", PassthroughNudgesGenerator)
