"""Pure KNN vector search retriever."""

from __future__ import annotations

from pipeline.retrieval.types import RetrievalQuery, SearchResult
from pipeline.retrieval.retrievers._shared import (
    build_filter_clauses,
    embed_query,
    run_opensearch_search,
)
from utils.embedding_fields import get_embedding_field_name
from utils.logging_config import get_logger

logger = get_logger(__name__)


class VectorRetriever:
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
        query_embeddings = await embed_query(query.text, client)

        knn_queries = []
        embedding_fields = []
        for model_name, embedding_vector in query_embeddings.items():
            field_name = get_embedding_field_name(model_name)
            embedding_fields.append(field_name)
            knn_queries.append({
                "knn": {
                    field_name: {
                        "vector": embedding_vector,
                        "k": 50,
                        "num_candidates": 1000,
                    }
                }
            })

        exists_filter = {
            "bool": {
                "should": [{"exists": {"field": f}} for f in embedding_fields],
                "minimum_should_match": 1,
            }
        }
        all_filters = [*filter_clauses, exists_filter]

        search_body = {
            "query": {
                "bool": {
                    "should": [{"dis_max": {"tie_breaker": 0.0, "queries": knn_queries}}],
                    "minimum_should_match": 1,
                    "filter": all_filters,
                }
            }
        }

        logger.info("VectorRetriever: searching", query_preview=query.text[:60])
        return await run_opensearch_search(client, search_body, query)
