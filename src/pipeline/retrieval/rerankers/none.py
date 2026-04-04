"""Pass-through reranker — returns results unchanged."""

from __future__ import annotations

from pipeline.retrieval.types import SearchResult


class PassthroughReranker:
    async def rerank(self, query: str, results: list[SearchResult]) -> list[SearchResult]:
        return results
