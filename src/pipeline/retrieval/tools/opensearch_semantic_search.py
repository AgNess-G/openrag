"""LangChain tool: KNN semantic search."""

from __future__ import annotations

from langchain_core.tools import BaseTool
from pydantic import Field

from pipeline.retrieval.types import RetrievalQuery


class SemanticSearchTool(BaseTool):
    name: str = "semantic_search"
    description: str = (
        "Find documents by conceptual/semantic similarity using KNN vector search. "
        "Best for 'find docs about X' style queries. "
        "Input: a natural language query string."
    )
    user_id: str | None = Field(default=None, exclude=True)
    jwt_token: str | None = Field(default=None, exclude=True)
    limit: int = Field(default=10, exclude=True)

    def _run(self, query: str) -> str:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(self._arun(query))

    async def _arun(self, query: str) -> str:
        from pipeline.retrieval.retrievers.opensearch_vector import VectorRetriever

        retriever = VectorRetriever()
        rq = RetrievalQuery(
            text=query,
            user_id=self.user_id,
            jwt_token=self.jwt_token,
            limit=self.limit,
        )
        results = await retriever.retrieve(rq)
        if not results:
            return "No results found."
        parts = []
        for i, r in enumerate(results, 1):
            parts.append(f"[{i}] {r.filename} (score={r.score:.3f})\n{r.text[:500]}")
        return "\n\n".join(parts)
