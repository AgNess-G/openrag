"""Raw OpenSearch DSL retriever — passes arbitrary query dict through as-is."""

from __future__ import annotations

from pipeline.retrieval.types import RetrievalQuery, SearchResult
from pipeline.retrieval.retrievers._shared import build_filter_clauses, run_opensearch_search
from utils.logging_config import get_logger

logger = get_logger(__name__)


class RawRetriever:
    """
    Accepts an arbitrary OpenSearch DSL query via query.filters["dsl_query"].
    If no dsl_query is provided, falls back to match_all with any other filters.

    Example usage:
        query.filters = {
            "dsl_query": {"match": {"text": "hello"}},
            "data_sources": ["doc.pdf"],
        }
    """

    def __init__(self, opensearch_client=None) -> None:
        self._opensearch_client = opensearch_client

    def _get_client(self, query: RetrievalQuery):
        if self._opensearch_client:
            return self._opensearch_client
        from config.settings import clients
        return clients.create_user_opensearch_client(query.jwt_token or "")

    async def retrieve(self, query: RetrievalQuery) -> list[SearchResult]:
        client = self._get_client(query)

        filters = query.filters or {}
        dsl_query = filters.pop("dsl_query", None) if filters else None

        filter_clauses = build_filter_clauses(filters)

        if dsl_query:
            if filter_clauses:
                search_body = {
                    "query": {
                        "bool": {
                            "must": [dsl_query],
                            "filter": filter_clauses,
                        }
                    }
                }
            else:
                search_body = {"query": dsl_query}
        else:
            if filter_clauses:
                search_body = {"query": {"bool": {"filter": filter_clauses}}}
            else:
                search_body = {"query": {"match_all": {}}}

        logger.info(
            "RawRetriever: searching",
            query_preview=query.text[:60],
            has_dsl_query=dsl_query is not None,
            filter_count=len(filter_clauses),
        )
        return await run_opensearch_search(client, search_body, query)
