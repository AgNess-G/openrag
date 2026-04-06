"""LangChain ReAct agent with composable tool support."""

from __future__ import annotations

import json
import uuid
from typing import AsyncIterator

from pipeline.retrieval.types import AgentResponse, ConversationMessage, SearchResult
from utils.logging_config import get_logger

logger = get_logger(__name__)

try:
    from langchain.agents import AgentExecutor, create_react_agent
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
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


def _to_langchain_history(history: list[ConversationMessage]) -> list:
    messages = []
    for m in history:
        if m.role == "user":
            messages.append(HumanMessage(content=m.content))
        elif m.role == "assistant":
            messages.append(AIMessage(content=m.content))
        elif m.role == "system":
            messages.append(SystemMessage(content=m.content))
    return messages


_REACT_PROMPT_TEMPLATE = """{system_prompt}

You have access to the following tools:

{tools}

Use the following format:

Question: the input question you must answer
Thought: you should always think about what to do
Action: the action to take, should be one of [{tool_names}]
Action Input: the input to the action
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

Context from retrieval:
{context}

Conversation history:
{chat_history}

Question: {input}
Thought: {agent_scratchpad}"""


class ReActAgent:
    def __init__(
        self,
        model: str = "gpt-4o",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        system_prompt: str = "",
        max_iterations: int = 10,
        tools: list[str] | None = None,
        tool_registry=None,
        **_kwargs,
    ) -> None:
        if not _AVAILABLE:
            raise ImportError(
                "langchain and langchain-openai are required for ReActAgent. "
                "Install with: pip install langchain langchain-openai"
            )
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._system_prompt = system_prompt
        self.max_iterations = max_iterations
        self._tool_names = tools or []
        self._tool_registry = tool_registry

    def _get_system_prompt(self) -> str:
        if self._system_prompt:
            return self._system_prompt
        return "You are a helpful assistant with access to a knowledge base. Use the available tools to find accurate answers."

    def _build_executor(self, lc_tools: list) -> AgentExecutor:
        from langchain_core.prompts import PromptTemplate

        llm = ChatOpenAI(
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        prompt = PromptTemplate.from_template(_REACT_PROMPT_TEMPLATE)
        agent = create_react_agent(llm, lc_tools, prompt)
        return AgentExecutor(
            agent=agent,
            tools=lc_tools,
            max_iterations=self.max_iterations,
            handle_parsing_errors=True,
            verbose=False,
        )

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
        chat_history_str = "\n".join(
            f"{m.role}: {m.content}" for m in history if m.role in ("user", "assistant")
        )

        executor = self._build_executor(lc_tools)
        try:
            result = await executor.ainvoke({
                "input": query,
                "context": context,
                "chat_history": chat_history_str,
                "system_prompt": self._get_system_prompt(),
            })
            response_text = result.get("output", "")
            # Gather sources from retrieved_docs + any tool-retrieved results
            sources = retrieved_docs
        except Exception as e:
            logger.error("ReActAgent: execution failed", error=str(e))
            raise

        response_id = str(uuid.uuid4())
        return AgentResponse(
            response=response_text,
            response_id=response_id,
            sources=sources,
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
        chat_history_str = "\n".join(
            f"{m.role}: {m.content}" for m in history if m.role in ("user", "assistant")
        )

        executor = self._build_executor(lc_tools)

        input_tokens = 0
        output_tokens = 0
        tool_inputs: dict[str, object] = {}  # run_id → input, to carry from start to end
        try:
            async for event in executor.astream_events(
                {
                    "input": query,
                    "context": context,
                    "chat_history": chat_history_str,
                    "system_prompt": self._get_system_prompt(),
                },
                version="v2",
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
            logger.error("ReActAgent: streaming failed", error=str(e))
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
