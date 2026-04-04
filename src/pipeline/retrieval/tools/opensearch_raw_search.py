"""LangChain tool: raw search with full DSL + filter support."""

from __future__ import annotations

import json

from langchain_core.tools import BaseTool
from pydantic import Field

from pipeline.retrieval.types import RetrievalQuery


class RawSearchTool(BaseTool):
    name: str = "raw_search"
    description: str = (
        "Search with filters or custom DSL. "
        "Input: JSON string with optional 'query' (text) and 'filters' keys. "
        "Filters support: owner, connector_type, data_sources (list), document_types (list), "
        "and dsl_query (raw OpenSearch query dict). "
        "Example: {\"query\": \"budget\", \"filters\": {\"owners\": [\"alice@corp.com\"]}} "
        "Best for structured/filtered lookups or when you need to scope by connector or owner."
    )
    user_id: str | None = Field(default=None, exclude=True)
    jwt_token: str | None = Field(default=None, exclude=True)
    limit: int = Field(default=10, exclude=True)

    def _run(self, input_json: str) -> str:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(self._arun(input_json))

    async def _arun(self, input_json: str) -> str:
        from pipeline.retrieval.retrievers.opensearch_raw import RawRetriever

        try:
            data = json.loads(input_json) if input_json.strip().startswith("{") else {"query": input_json}
        except (json.JSONDecodeError, ValueError):
            data = {"query": input_json}

        query_text = data.get("query", "")
        filters = data.get("filters", {})

        retriever = RawRetriever()
        rq = RetrievalQuery(
            text=query_text,
            user_id=self.user_id,
            jwt_token=self.jwt_token,
            filters=filters if filters else None,
            limit=self.limit,
        )
        results = await retriever.retrieve(rq)
        if not results:
            return "No results found."
        parts = []
        for i, r in enumerate(results, 1):
            parts.append(f"[{i}] {r.filename} (score={r.score:.3f})\n{r.text[:500]}")
        return "\n\n".join(parts)
