"""Deep agent using the `deepagents` SDK (create_deep_agent).

Built on LangGraph with built-in planning (write_todos), virtual filesystem,
and subagent spawning for complex multi-step research tasks.
"""

from __future__ import annotations

import json
import uuid
from typing import AsyncIterator

from pipeline.retrieval.types import AgentResponse, ConversationMessage, SearchResult
from utils.logging_config import get_logger

logger = get_logger(__name__)

try:
    from deepagents import create_deep_agent
    from langchain.chat_models import init_chat_model

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


def _build_system_prompt(base_prompt: str, context: str) -> str:
    system = base_prompt or (
        "You are a research assistant. Plan your approach carefully using write_todos, "
        "then use the available tools to find accurate, comprehensive answers. "
        "When you have enough information, synthesise a complete response."
    )
    if context:
        system = (
            f"{system}\n\n"
            f"Initial retrieval context (use as a starting point, search further as needed):\n"
            f"{context}"
        )
    return system


class DeepAgent:
    def __init__(
        self,
        model: str = "openai:gpt-4o",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        system_prompt: str = "",
        tools: list[str] | None = None,
        tool_registry=None,
        max_iterations: int = 10,
        **_kwargs,
    ) -> None:
        if not _AVAILABLE:
            raise ImportError(
                "deepagents is required for DeepAgent. "
                "Install with: pip install deepagents"
            )
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._system_prompt = system_prompt
        self._tool_names = tools or []
        self._tool_registry = tool_registry
        self.max_iterations = max_iterations

    async def run(
        self,
        query: str,
        retrieved_docs: list[SearchResult],
        history: list[ConversationMessage],
        user_id: str | None = None,
        jwt_token: str | None = None,
    ) -> AgentResponse:
        from pipeline.retrieval.tools.registry import ToolRegistry

        registry = self._tool_registry or ToolRegistry.get_default()
        lc_tools = registry.get_tools(self._tool_names, user_id=user_id, jwt_token=jwt_token)

        context = _format_context(retrieved_docs)
        system_prompt = _build_system_prompt(self._system_prompt, context)

        # Build LangChain chat model with temperature / max_tokens
        llm = init_chat_model(
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

        agent = create_deep_agent(
            model=llm,
            tools=lc_tools,
            system_prompt=system_prompt,
        )

        # Build messages list — prepend conversation history
        messages = [
            {"role": msg.role, "content": msg.content}
            for msg in history
        ]
        messages.append({"role": "user", "content": query})

        try:
            result = await agent.ainvoke({"messages": messages})
        except Exception as e:
            logger.error("DeepAgent: execution failed", error=str(e))
            raise

        # Response is the last message in the returned messages list
        last_message = result["messages"][-1]
        response_text = (
            last_message.content
            if hasattr(last_message, "content")
            else str(last_message)
        )

        response_id = str(uuid.uuid4())
        return AgentResponse(
            response=response_text,
            response_id=response_id,
            sources=retrieved_docs,
            usage={},
        )

    async def run_stream(
        self,
        query: str,
        retrieved_docs: list[SearchResult],
        history: list[ConversationMessage],
        user_id: str | None = None,
        jwt_token: str | None = None,
    ) -> AsyncIterator[str]:
        from pipeline.retrieval.tools.registry import ToolRegistry

        registry = self._tool_registry or ToolRegistry.get_default()
        lc_tools = registry.get_tools(self._tool_names, user_id=user_id, jwt_token=jwt_token)

        context = _format_context(retrieved_docs)
        system_prompt = _build_system_prompt(self._system_prompt, context)

        llm = init_chat_model(
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

        agent = create_deep_agent(
            model=llm,
            tools=lc_tools,
            system_prompt=system_prompt,
        )

        messages = [{"role": msg.role, "content": msg.content} for msg in history]
        messages.append({"role": "user", "content": query})

        input_tokens = 0
        output_tokens = 0
        tool_inputs: dict[str, object] = {}  # run_id → input, to carry from start to end
        try:
            async for event in agent.astream_events(
                {"messages": messages}, version="v2"
            ):
                kind = event["event"]
                if kind == "on_chat_model_stream":
                    chunk = event["data"].get("chunk")
                    if chunk and chunk.content:
                        yield json.dumps({"delta": chunk.content}) + "\n"
                elif kind == "on_tool_start":
                    tool_name = event.get("name", "tool")
                    run_id = event.get("run_id", str(uuid.uuid4()))
                    tool_input = event.get("data", {}).get("input", "")
                    tool_inputs[run_id] = tool_input
                    inputs_dict = {"query": tool_input} if isinstance(tool_input, str) else (tool_input or {})
                    yield json.dumps({
                        "type": "response.output_item.added",
                        "item": {
                            "type": "tool_call",
                            "id": run_id,
                            "name": tool_name,
                            "status": "pending",
                            "inputs": inputs_dict,
                        },
                    }) + "\n"
                elif kind == "on_tool_end":
                    tool_name = event.get("name", "tool")
                    run_id = event.get("run_id", str(uuid.uuid4()))
                    raw_output = event.get("data", {}).get("output", "")
                    tool_input = tool_inputs.pop(run_id, "")
                    inputs_dict = {"query": tool_input} if isinstance(tool_input, str) else (tool_input or {})
                    # Try to parse output as structured search results, fall back to plain text
                    try:
                        parsed = json.loads(str(raw_output)) if isinstance(raw_output, str) else raw_output
                        if isinstance(parsed, list):
                            results = [
                                {"filename": r.get("filename", ""), "text": r.get("text", ""), "score": r.get("score")}
                                for r in parsed
                                if isinstance(r, dict)
                            ]
                        else:
                            results = [{"text": str(raw_output)}]
                    except (json.JSONDecodeError, TypeError):
                        results = [{"text": str(raw_output)[:2000]}]
                    yield json.dumps({
                        "type": "response.output_item.done",
                        "item": {
                            "type": "tool_call",
                            "id": run_id,
                            "name": tool_name,
                            "status": "completed",
                            "inputs": inputs_dict,
                            "results": results,
                        },
                    }) + "\n"
                elif kind == "on_chat_model_end":
                    llm_output = event["data"].get("output")
                    if llm_output and hasattr(llm_output, "usage_metadata"):
                        meta = llm_output.usage_metadata
                        input_tokens += meta.get("input_tokens", 0)
                        output_tokens += meta.get("output_tokens", 0)
        except Exception as e:
            logger.error("DeepAgent: streaming failed", error=str(e))
            raise

        if input_tokens or output_tokens:
            yield json.dumps({
                "type": "response.completed",
                "response": {
                    "usage": {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "total_tokens": input_tokens + output_tokens,
                    }
                },
            }) + "\n"
