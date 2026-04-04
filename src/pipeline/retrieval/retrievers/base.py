"""Base protocol for retrievers."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pipeline.retrieval.types import RetrievalQuery, SearchResult


@runtime_checkable
class Retriever(Protocol):
    async def retrieve(self, query: RetrievalQuery) -> list[SearchResult]:
        ...
