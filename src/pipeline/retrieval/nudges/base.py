"""Base protocol for nudges generators."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pipeline.retrieval.types import ConversationMessage, RetrievalQuery


@runtime_checkable
class NudgesGenerator(Protocol):
    async def generate(
        self,
        query: RetrievalQuery,
        history: list[ConversationMessage],
    ) -> list[str]:
        ...
