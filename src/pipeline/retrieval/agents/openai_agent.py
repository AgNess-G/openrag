"""OpenAI Responses API agent — preserves current behaviour."""

from __future__ import annotations

import json
import uuid
from typing import AsyncIterator

from config.settings import clients, get_openrag_config
from pipeline.retrieval.types import AgentResponse, ConversationMessage, SearchResult
from utils.logging_config import get_logger

logger = get_logger(__name__)


def _format_context(docs: list[SearchResult]) -> str:
    if not docs:
        return ""
    parts = []
    for i, doc in enumerate(docs, 1):
        source = doc.filename or doc.source_url or f"doc_{i}"
        parts.append(f"[{i}] Source: {source}\n{doc.text}")
    return "\n\n".join(parts)


def _format_history(history: list[ConversationMessage]) -> list[dict]:
    return [{"role": m.role, "content": m.content} for m in history if m.role in ("user", "assistant")]


class OpenAIAgent:
    def __init__(
        self,
        model: str = "gpt-4o",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        system_prompt: str = "",
        **_kwargs,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._system_prompt = system_prompt

    def _get_system_prompt(self) -> str:
        if self._system_prompt:
            return self._system_prompt
        try:
            config = get_openrag_config()
            sp = getattr(getattr(config, "agent", None), "system_prompt", "")
            return sp or "You are a helpful assistant. Answer questions using the provided context."
        except Exception:
            return "You are a helpful assistant. Answer questions using the provided context."

    async def run(
        self,
        query: str,
        retrieved_docs: list[SearchResult],
        history: list[ConversationMessage],
        user_id: str | None = None,
        jwt_token: str | None = None,
    ) -> AgentResponse:
        context = _format_context(retrieved_docs)
        system_prompt = self._get_system_prompt()

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(_format_history(history))

        user_content = query
        if context:
            user_content = f"Context:\n{context}\n\nQuestion: {query}"
        messages.append({"role": "user", "content": user_content})

        try:
            response = await clients.patched_llm_client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            response_text = response.choices[0].message.content or ""
            usage = {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        except Exception as e:
            logger.error("OpenAIAgent: chat completion failed", error=str(e))
            raise

        response_id = str(uuid.uuid4())
        return AgentResponse(
            response=response_text,
            response_id=response_id,
            sources=retrieved_docs,
            usage=usage,
        )

    async def run_stream(
        self,
        query: str,
        retrieved_docs: list[SearchResult],
        history: list[ConversationMessage],
        user_id: str | None = None,
        jwt_token: str | None = None,
    ) -> AsyncIterator[str]:
        context = _format_context(retrieved_docs)
        system_prompt = self._get_system_prompt()

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(_format_history(history))

        user_content = query
        if context:
            user_content = f"Context:\n{context}\n\nQuestion: {query}"
        messages.append({"role": "user", "content": user_content})

        try:
            stream = await clients.patched_llm_client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=True,
                stream_options={"include_usage": True},
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    yield json.dumps({"delta": delta}) + "\n"
                if getattr(chunk, "usage", None):
                    yield json.dumps({
                        "type": "response.completed",
                        "response": {
                            "usage": {
                                "input_tokens": chunk.usage.prompt_tokens,
                                "output_tokens": chunk.usage.completion_tokens,
                                "total_tokens": chunk.usage.total_tokens,
                            }
                        },
                    }) + "\n"
        except Exception as e:
            logger.error("OpenAIAgent: streaming failed", error=str(e))
            raise
