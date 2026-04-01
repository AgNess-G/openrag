"""Deduplication preprocessor using content hashing."""

from __future__ import annotations

import hashlib
from dataclasses import replace

from pipeline.types import ParsedDocument


class DuplicateDocumentError(Exception):
    """Raised when a document is detected as a duplicate."""

    def __init__(self, content_hash: str):
        self.content_hash = content_hash
        super().__init__(f"Duplicate document detected: {content_hash}")


class DedupPreprocessor:
    """Check for duplicate documents by content hash against OpenSearch."""

    def __init__(
        self,
        strategy: str = "content_hash",
        opensearch_client=None,
    ) -> None:
        self._strategy = strategy
        self._client = opensearch_client

    async def process(self, doc: ParsedDocument) -> ParsedDocument:
        content_hash = hashlib.sha256(doc.content.encode("utf-8")).hexdigest()

        if self._client is not None and self._strategy == "content_hash":
            exists = await self._check_exists(content_hash)
            if exists:
                raise DuplicateDocumentError(content_hash)

        updated_meta = {**doc.metadata, "content_hash": content_hash}
        return replace(doc, metadata=updated_meta)

    async def _check_exists(self, content_hash: str) -> bool:
        import asyncio

        from config.settings import get_index_name

        max_retries = 3
        retry_delay = 1.0

        for attempt in range(max_retries):
            try:
                return await self._client.exists(
                    index=get_index_name(), id=content_hash
                )
            except (asyncio.TimeoutError, Exception):
                if attempt == max_retries - 1:
                    return False
                await asyncio.sleep(retry_delay)
                retry_delay *= 2
