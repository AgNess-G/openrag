"""OpenSearch bulk indexer."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from pipeline.ingestion.types import EmbeddedChunk, FileMetadata, IndexResult
from utils.logging_config import get_logger

logger = get_logger(__name__)


class OpenSearchBulkIndexer:
    """Index embedded chunks into OpenSearch via the _bulk API."""

    def __init__(
        self,
        opensearch_client=None,
        bulk_batch_size: int = 500,
        retry_attempts: int = 3,
        retry_backoff: float = 2.0,
    ) -> None:
        self._client = opensearch_client
        self._batch_size = bulk_batch_size
        self._retry_attempts = retry_attempts
        self._retry_backoff = retry_backoff

    def _resolve_client(self):
        if self._client is not None:
            return self._client
        from config.settings import clients
        return getattr(clients, "opensearch", None)

    async def index(
        self, chunks: list[EmbeddedChunk], metadata: FileMetadata
    ) -> IndexResult:
        from config.settings import get_index_name
        from utils.embedding_fields import (
            ensure_embedding_field_exists,
            get_embedding_field_name,
        )

        if not chunks:
            return IndexResult(
                document_id=metadata.file_hash,
                chunks_indexed=0,
                index_name=get_index_name(),
                status="skipped",
            )

        index_name = get_index_name()
        model_name = chunks[0].embedding_model

        client = self._resolve_client()
        if client is None:
            raise RuntimeError(
                "OpenSearch client is not initialized; cannot index documents"
            )

        await ensure_embedding_field_exists(client, model_name, index_name)
        embed_field = get_embedding_field_name(model_name)

        actions = self._build_actions(
            chunks, metadata, index_name, embed_field
        )

        step = self._batch_size * 2
        num_batches = (len(actions) + step - 1) // step if actions else 0
        logger.info(
            "OpenSearch bulk indexer: starting bulk writes",
            file=metadata.filename,
            chunk_count=len(chunks),
            bulk_batches=num_batches,
            index=index_name,
            embedding_field=embed_field,
        )

        indexed = 0
        for batch_start in range(0, len(actions), self._batch_size * 2):
            batch = actions[batch_start : batch_start + self._batch_size * 2]
            batch_num = batch_start // step + 1
            logger.info(
                "OpenSearch bulk: sending batch",
                file=metadata.filename,
                batch_num=batch_num,
                of=max(num_batches, 1),
                ops=len(batch) // 2,
            )
            indexed += await self._send_bulk(client, batch, index_name)

        logger.info(
            "OpenSearch bulk indexer: finished",
            file=metadata.filename,
            chunks_indexed=indexed,
        )

        return IndexResult(
            document_id=metadata.file_hash,
            chunks_indexed=indexed,
            index_name=index_name,
        )

    def _build_actions(
        self,
        chunks: list[EmbeddedChunk],
        metadata: FileMetadata,
        index_name: str,
        embed_field: str,
    ) -> list[dict]:
        actions: list[dict] = []
        now = datetime.now(timezone.utc).isoformat()

        acl = metadata.acl or {}
        owner = metadata.owner_user_id or acl.get("owner", "")
        allowed_users = acl.get("allowed_users", [owner] if owner else [])
        allowed_groups = acl.get("allowed_groups", [])

        doc_id_base = metadata.document_id or metadata.file_hash

        for chunk in chunks:
            doc_id = f"{doc_id_base}_{chunk.index}"
            actions.append({"index": {"_index": index_name, "_id": doc_id}})
            body: dict = {
                "document_id": doc_id_base,
                "filename": metadata.filename,
                "mimetype": metadata.mimetype,
                "page": chunk.page,
                "text": chunk.text,
                "chunk_type": chunk.chunk_type,
                "chunk_index": chunk.index,
                "embedding_model": chunk.embedding_model,
                "embedding_dimensions": chunk.embedding_dimensions,
                embed_field: chunk.embedding,
                "file_size": metadata.file_size,
                "connector_type": metadata.connector_type,
                "indexed_time": now,
                "owner": owner,
                "allowed_users": allowed_users,
                "allowed_groups": allowed_groups,
            }
            if metadata.owner_name:
                body["owner_name"] = metadata.owner_name
            if metadata.owner_email:
                body["owner_email"] = metadata.owner_email
            if metadata.source_url:
                body["source_url"] = metadata.source_url
            if metadata.is_sample_data:
                body["is_sample_data"] = True
            actions.append(body)
        return actions

    async def _send_bulk(
        self, client, actions: list[dict], index_name: str
    ) -> int:
        last_exc: Exception | None = None
        for attempt in range(self._retry_attempts):
            try:
                resp = await client.bulk(body=actions, index=index_name)
                if resp.get("errors"):
                    failed = sum(
                        1 for item in resp.get("items", [])
                        if "error" in item.get("index", {})
                    )
                    return (len(actions) // 2) - failed
                return len(actions) // 2
            except Exception as exc:
                last_exc = exc
                if attempt < self._retry_attempts - 1:
                    await asyncio.sleep(
                        self._retry_backoff * (2 ** attempt)
                    )

        raise RuntimeError(
            f"Bulk indexing failed after {self._retry_attempts} attempts"
        ) from last_exc
