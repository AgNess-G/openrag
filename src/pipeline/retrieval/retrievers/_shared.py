"""Shared helpers for OpenSearch-based retrievers."""

from __future__ import annotations

import asyncio
from typing import Any

from config.settings import EMBED_MODEL, clients, get_embedding_model, get_index_name, WATSONX_EMBEDDING_DIMENSIONS
from pipeline.retrieval.types import RetrievalQuery, SearchResult
from utils.embedding_fields import get_embedding_field_name
from utils.logging_config import get_logger

logger = get_logger(__name__)

MAX_EMBED_RETRIES = 3
EMBED_RETRY_INITIAL_DELAY = 1.0
EMBED_RETRY_MAX_DELAY = 8.0

# Frontend filter key → OpenSearch field name
FILTER_FIELD_MAPPING = {
    "data_sources": "filename",
    "document_types": "mimetype",
    "owners": "owner",
    "connector_types": "connector_type",
}

SOURCE_FIELDS = [
    "filename",
    "mimetype",
    "page",
    "text",
    "source_url",
    "owner",
    "owner_name",
    "owner_email",
    "file_size",
    "connector_type",
    "embedding_model",
]


def build_filter_clauses(filters: dict | None) -> list[dict]:
    """Convert frontend filter dict to OpenSearch bool.filter clauses."""
    if not filters:
        return []
    clauses = []
    for filter_key, values in filters.items():
        if not isinstance(values, list):
            continue
        field_name = FILTER_FIELD_MAPPING.get(filter_key, filter_key)
        if len(values) == 0:
            clauses.append({"term": {field_name: "__IMPOSSIBLE_VALUE__"}})
        elif len(values) == 1:
            clauses.append({"term": {field_name: values[0]}})
        else:
            clauses.append({"terms": {field_name: values}})
    return clauses


def hit_to_search_result(hit: dict) -> SearchResult:
    """Convert an OpenSearch hit dict to a SearchResult."""
    src = hit.get("_source", {})
    return SearchResult(
        text=src.get("text", ""),
        filename=src.get("filename", ""),
        score=hit.get("_score", 0.0),
        page=src.get("page"),
        mimetype=src.get("mimetype", ""),
        source_url=src.get("source_url"),
        owner=src.get("owner"),
        owner_name=src.get("owner_name"),
        owner_email=src.get("owner_email"),
        connector_type=src.get("connector_type"),
        document_id=hit.get("_id"),
        metadata={
            "embedding_model": src.get("embedding_model"),
            "file_size": src.get("file_size"),
        },
    )


async def embed_query(query_text: str, opensearch_client) -> dict[str, list[float]]:
    """
    Embed a query against all embedding models detected in the corpus.
    Returns {model_name: embedding_vector}.
    """
    embedding_model = get_embedding_model() or EMBED_MODEL

    # Detect available models from corpus
    try:
        agg_result = await opensearch_client.search(
            index=get_index_name(),
            body={
                "size": 0,
                "aggs": {"embedding_models": {"terms": {"field": "embedding_model", "size": 10}}},
            },
            params={"terminate_after": 0},
        )
        buckets = agg_result.get("aggregations", {}).get("embedding_models", {}).get("buckets", [])
        available_models = [b["key"] for b in buckets if b["key"]] or [embedding_model]
    except Exception as e:
        logger.warning("Failed to detect embedding models, using configured model", error=str(e))
        available_models = [embedding_model]

    async def embed_with_model(model_name: str) -> tuple[str, list[float]]:
        formatted = model_name
        if not any(model_name.startswith(p + "/") for p in ["openai", "ollama", "watsonx", "anthropic"]):
            if ":" in model_name:
                formatted = f"ollama/{model_name}"
            elif model_name in WATSONX_EMBEDDING_DIMENSIONS:
                formatted = f"watsonx/{model_name}"

        delay = EMBED_RETRY_INITIAL_DELAY
        for attempt in range(1, MAX_EMBED_RETRIES + 1):
            try:
                resp = await clients.patched_embedding_client.embeddings.create(
                    model=formatted, input=[query_text]
                )
                embedding = getattr(resp.data[0], "embedding", None)
                if embedding is None:
                    embedding = resp.data[0]["embedding"]
                return model_name, embedding
            except Exception as e:
                if attempt >= MAX_EMBED_RETRIES:
                    raise RuntimeError(f"Failed to embed with model {model_name}") from e
                await asyncio.sleep(delay)
                delay = min(delay * 2, EMBED_RETRY_MAX_DELAY)

    results = await asyncio.gather(*[embed_with_model(m) for m in available_models])
    return {model: vec for model, vec in results}


async def run_opensearch_search(
    opensearch_client,
    search_body: dict,
    query: RetrievalQuery,
) -> list[SearchResult]:
    """Execute a search and return SearchResult list."""
    from opensearchpy.exceptions import RequestError
    from utils.opensearch_utils import OpenSearchDiskSpaceError, is_disk_space_error, DISK_SPACE_ERROR_MESSAGE
    import copy

    if query.score_threshold > 0:
        search_body["min_score"] = query.score_threshold
    search_body["size"] = query.limit
    search_body["_source"] = SOURCE_FIELDS

    # Build fallback without num_candidates
    try:
        fallback_body = copy.deepcopy(search_body)
        for q in fallback_body.get("query", {}).get("bool", {}).get("should", [{}])[:1]:
            for dq in q.get("dis_max", {}).get("queries", []):
                for params in dq.get("knn", {}).values():
                    if isinstance(params, dict):
                        params.pop("num_candidates", None)
    except Exception:
        fallback_body = None

    try:
        results = await opensearch_client.search(
            index=get_index_name(), body=search_body, params={"terminate_after": 0}
        )
    except RequestError as e:
        if is_disk_space_error(e):
            raise OpenSearchDiskSpaceError(DISK_SPACE_ERROR_MESSAGE) from e
        if fallback_body and "unknown field [num_candidates]" in str(e).lower():
            logger.warning("Retrying without num_candidates")
            results = await opensearch_client.search(
                index=get_index_name(), body=fallback_body, params={"terminate_after": 0}
            )
        else:
            raise

    return [hit_to_search_result(h) for h in results["hits"]["hits"]]
