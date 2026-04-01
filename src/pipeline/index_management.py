"""Composable-mode OpenSearch index creation and management.

This module provides index creation for composable pipeline mode,
using PipelineConfig as the source of truth for embedding model and
provider settings. It does not depend on Langflow.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.logging_config import get_logger

if TYPE_CHECKING:
    from pipeline.config import PipelineConfig

logger = get_logger(__name__)

KNOWLEDGE_FILTERS_INDEX_BODY = {
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "name": {"type": "text", "analyzer": "standard"},
            "description": {"type": "text", "analyzer": "standard"},
            "query_data": {"type": "text"},
            "owner": {"type": "keyword"},
            "allowed_users": {"type": "keyword"},
            "allowed_groups": {"type": "keyword"},
            "subscriptions": {"type": "object"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
        }
    }
}


async def init_composable_index(
    opensearch_client,
    pipeline_config: PipelineConfig,
) -> str:
    """Create or ensure the OpenSearch index exists for composable mode.

    Uses the embedder settings from PipelineConfig (model, provider) to
    resolve embedding dimensions and create the appropriate dynamic
    ``chunk_embedding_{model}`` field.

    Returns the documents index name.
    """
    from config.settings import (
        API_KEYS_INDEX_BODY,
        API_KEYS_INDEX_NAME,
        get_index_name,
    )
    from utils.embeddings import create_dynamic_index_body
    from utils.embedding_fields import ensure_embedding_field_exists

    embedding_model = pipeline_config.embedder.model
    embedding_provider = pipeline_config.embedder.provider

    endpoint = _resolve_provider_endpoint(pipeline_config)

    dynamic_index_body = await create_dynamic_index_body(
        embedding_model,
        provider=embedding_provider,
        endpoint=endpoint,
    )

    index_name = get_index_name()

    if not await opensearch_client.indices.exists(index=index_name):
        await opensearch_client.indices.create(
            index=index_name, body=dynamic_index_body
        )
        logger.info(
            "Created OpenSearch index (composable)",
            index_name=index_name,
            embedding_model=embedding_model,
        )
    else:
        logger.info(
            "Index already exists, ensuring embedding field",
            index_name=index_name,
            embedding_model=embedding_model,
        )
        await ensure_embedding_field_exists(
            opensearch_client, embedding_model, index_name
        )

    # Knowledge filters index
    kf_index = "knowledge_filters"
    if not await opensearch_client.indices.exists(index=kf_index):
        await opensearch_client.indices.create(
            index=kf_index, body=KNOWLEDGE_FILTERS_INDEX_BODY
        )
        logger.info("Created knowledge filters index (composable)")

    # API keys index
    if not await opensearch_client.indices.exists(index=API_KEYS_INDEX_NAME):
        await opensearch_client.indices.create(
            index=API_KEYS_INDEX_NAME, body=API_KEYS_INDEX_BODY
        )
        logger.info("Created API keys index (composable)")

    return index_name


def _resolve_provider_endpoint(pipeline_config: PipelineConfig) -> str | None:
    """Return the Ollama endpoint if the embedder uses Ollama, else None."""
    import os

    if pipeline_config.embedder.provider == "ollama":
        return os.getenv("OLLAMA_BASE_URL") or os.getenv(
            "OLLAMA_ENDPOINT", "http://localhost:11434"
        )
    return None
