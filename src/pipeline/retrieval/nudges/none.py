"""Pass-through nudges generator — returns empty list."""

from __future__ import annotations

from pipeline.retrieval.types import ConversationMessage, RetrievalQuery


class PassthroughNudgesGenerator:
    async def generate(
        self,
        query: RetrievalQuery,
        history: list[ConversationMessage],
    ) -> list[str]:
        return []
