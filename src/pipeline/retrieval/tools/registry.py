"""Tool registry mapping names to LangChain BaseTool instances."""

from __future__ import annotations

from typing import Any

from utils.logging_config import get_logger

logger = get_logger(__name__)

_TOOL_FACTORIES: dict[str, type] = {}


class ToolRegistry:
    """Maps tool name → LangChain BaseTool class."""

    def __init__(self) -> None:
        self._tools: dict[str, Any] = {}

    def register(self, name: str, tool_cls: type) -> None:
        self._tools[name] = tool_cls

    def get_tool(self, name: str, **kwargs) -> Any:
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' not registered. Available: {list(self._tools.keys())}")
        return self._tools[name](**kwargs)

    def get_tools(self, names: list[str], **kwargs) -> list:
        tools = []
        for name in names:
            try:
                tools.append(self.get_tool(name, **kwargs))
            except KeyError:
                logger.warning("Tool not found, skipping", tool_name=name)
        return tools

    @classmethod
    def get_default(cls) -> "ToolRegistry":
        return _get_default_registry()


_default_registry: ToolRegistry | None = None


def _get_default_registry() -> ToolRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = ToolRegistry()
        _populate_defaults(_default_registry)
    return _default_registry


def _populate_defaults(registry: ToolRegistry) -> None:
    from pipeline.retrieval.tools.opensearch_semantic_search import SemanticSearchTool
    from pipeline.retrieval.tools.opensearch_keyword_search import KeywordSearchTool
    from pipeline.retrieval.tools.opensearch_hybrid_search import HybridSearchTool
    from pipeline.retrieval.tools.opensearch_raw_search import RawSearchTool
    from pipeline.retrieval.tools.get_document import GetDocumentTool
    from pipeline.retrieval.tools.list_sources import ListSourcesTool
    from pipeline.retrieval.tools.calculator import CalculatorTool

    registry.register("semantic_search", SemanticSearchTool)
    registry.register("keyword_search", KeywordSearchTool)
    registry.register("hybrid_search", HybridSearchTool)
    registry.register("raw_search", RawSearchTool)
    registry.register("get_document", GetDocumentTool)
    registry.register("list_sources", ListSourcesTool)
    registry.register("calculator", CalculatorTool)
