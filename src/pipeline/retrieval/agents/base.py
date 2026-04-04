"""Base protocol for agents."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pipeline.retrieval.types import AgentResponse, ConversationMessage, SearchResult


@runtime_checkable
class Agent(Protocol):
    async def run(
        self,
        query: str,
        retrieved_docs: list[SearchResult],
        history: list[ConversationMessage],
    ) -> AgentResponse:
        ...
