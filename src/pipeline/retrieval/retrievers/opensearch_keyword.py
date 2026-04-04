"""Pure multi_match keyword search retriever."""

from __future__ import annotations

from pipeline.retrieval.types import RetrievalQuery, SearchResult
from pipeline.retrieval.retrievers._shared import build_filter_clauses, run_opensearch_search
from utils.logging_config import get_logger

logger = get_logger(__name__)


class KeywordRetriever:
    def __init__(self, opensearch_client=None) -> None:
        self._opensearch_client = opensearch_client

    def _get_client(self, query: RetrievalQuery):
        if self._opensearch_client:
            return self._opensearch_client
        from config.settings import clients
        return clients.create_user_opensearch_client(query.jwt_token or "")

    async def retrieve(self, query: RetrievalQuery) -> list[SearchResult]:
        client = self._get_client(query)
        filter_clauses = build_filter_clauses(query.filters)

        search_body: dict = {
            "query": {
                "bool": {
                    "should": [
                        {
                            "multi_match": {
                                "query": query.text,
                                "fields": ["text^2", "filename^1.5"],
                                "type": "best_fields",
                                "operator": "or",
                                "fuzziness": "AUTO:4,7",
                            }
                        },
                        {
                            "match_phrase_prefix": {
                                "text": {"query": query.text, "max_expansions": 50}
                            }
                        },
                    ],
                    "minimum_should_match": 1,
                }
            }
        }
        if filter_clauses:
            search_body["query"]["bool"]["filter"] = filter_clauses

        logger.info("KeywordRetriever: searching", query_preview=query.text[:60])
        return await run_opensearch_search(client, search_body, query)
