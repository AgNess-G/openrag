"""Base protocol for rerankers."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pipeline.retrieval.types import SearchResult


@runtime_checkable
class Reranker(Protocol):
    async def rerank(self, query: str, results: list[SearchResult]) -> list[SearchResult]:
        ...
