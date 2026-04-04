"""LangChain plan-and-execute (deep research) agent."""

from __future__ import annotations

import uuid

from pipeline.retrieval.types import AgentResponse, ConversationMessage, SearchResult
from utils.logging_config import get_logger

logger = get_logger(__name__)

try:
    from langchain_experimental.plan_and_execute import (
        PlanAndExecute,
        load_agent_executor,
        load_chat_planner,
    )
    from langchain_openai import ChatOpenAI

    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


def _format_context(docs: list[SearchResult]) -> str:
    if not docs:
        return ""
    parts = []
    for i, doc in enumerate(docs, 1):
        source = doc.filename or doc.source_url or f"doc_{i}"
        parts.append(f"[{i}] Source: {source}\n{doc.text}")
    return "\n\n".join(parts)


class DeepAgent:
    def __init__(
        self,
        model: str = "gpt-4o",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        system_prompt: str = "",
        tools: list[str] | None = None,
        tool_registry=None,
        **_kwargs,
    ) -> None:
        if not _AVAILABLE:
            raise ImportError(
                "langchain-experimental is required for DeepAgent. "
                "Install with: pip install langchain-experimental"
            )
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._system_prompt = system_prompt
        self._tool_names = tools or []
        self._tool_registry = tool_registry

    def _get_system_prompt(self) -> str:
        if self._system_prompt:
            return self._system_prompt
        return "You are a research assistant. Plan your approach carefully and use the available tools to find accurate, comprehensive answers."

    async def run(
        self,
        query: str,
        retrieved_docs: list[SearchResult],
        history: list[ConversationMessage],
    ) -> AgentResponse:
        from pipeline.retrieval.tools.registry import ToolRegistry

        registry = self._tool_registry or ToolRegistry.get_default()
        lc_tools = registry.get_tools(self._tool_names)

        context = _format_context(retrieved_docs)
        augmented_query = query
        if context:
            augmented_query = f"Context from initial retrieval:\n{context}\n\nQuestion: {query}"

        llm = ChatOpenAI(
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        planner = load_chat_planner(llm, system_prompt=self._get_system_prompt())
        executor = load_agent_executor(llm, lc_tools, verbose=False)
        agent = PlanAndExecute(planner=planner, executor=executor)

        try:
            result = await agent.ainvoke({"input": augmented_query})
            response_text = result.get("output", "")
        except Exception as e:
            logger.error("DeepAgent: execution failed", error=str(e))
            raise

        response_id = str(uuid.uuid4())
        return AgentResponse(
            response=response_text,
            response_id=response_id,
            sources=retrieved_docs,
            usage={},
        )
