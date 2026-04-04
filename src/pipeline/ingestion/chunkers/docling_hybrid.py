"""Docling hybrid chunker — uses docling-serve /v1/chunk/hybrid/file when available.

When docling-serve is reachable and the original file path is known, this
chunker delegates entirely to docling's HybridChunker, which produces
structure-aware, token-bounded chunks with heading context.

Fallback behaviour
------------------
If docling-serve is unreachable, not configured, or the file path is missing,
the chunker falls back to page/table splitting + RecursiveCharacterTextSplitter.
This mirrors the old DoclingHybridChunker behaviour and keeps PDF pipelines
working in local-only environments.
"""

from __future__ import annotations

import os
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter

from pipeline.ingestion.types import Chunk, ParsedDocument
from utils.logging_config import get_logger

logger = get_logger(__name__)


class DoclingHybridChunker:
    """Chunk via docling-serve HybridChunker, with local fallback."""

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        max_tokens: int = 512,
        service_url: str | None = None,
    ) -> None:
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._max_tokens = max_tokens
        self._service_url = (
            service_url
            or os.getenv("DOCLING_SERVE_URL")
            or os.getenv("DOCLING_SERVICE_URL")
            or "http://localhost:5001"
        )
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", " ", ""],
        )

    async def chunk(self, doc: ParsedDocument) -> list[Chunk]:
        if doc.file_path and self._service_url:
            try:
                return await self._chunk_via_docling_serve(doc)
            except Exception as e:
                logger.warning(
                    "DoclingHybridChunker: docling-serve unavailable, using fallback",
                    error=str(e),
                    file=doc.filename,
                )
        return await self._chunk_fallback(doc)

    async def _chunk_via_docling_serve(self, doc: ParsedDocument) -> list[Chunk]:
        import httpx

        path = Path(doc.file_path)
        file_bytes = path.read_bytes()

        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                f"{self._service_url}/v1/chunk/hybrid/file",
                files={"files": (path.name, file_bytes)},
                data={"max_tokens": str(self._max_tokens)},
            )
            response.raise_for_status()

        raw_chunks = response.json().get("chunks", [])

        logger.debug(
            "DoclingHybridChunker: received chunks from docling-serve",
            file=doc.filename,
            chunk_count=len(raw_chunks),
        )

        chunks: list[Chunk] = []
        for i, c in enumerate(raw_chunks):
            text = c.get("text", "").strip()
            if not text:
                continue
            headings: list[str] = c.get("headings", [])
            chunks.append(Chunk(
                text=text,
                index=i,
                source=doc.filename,
                chunk_type="text",
                metadata={
                    "headings": headings,
                    "heading": headings[-1] if headings else None,
                    "doc_items": c.get("doc_items", []),
                },
            ))
        return chunks

    async def _chunk_fallback(self, doc: ParsedDocument) -> list[Chunk]:
        """Original page/table split + recursive text split."""
        chunks: list[Chunk] = []
        idx = 0

        if doc.pages:
            for page_data in doc.pages:
                text = page_data.get("text", "")
                page_no = page_data.get("page")
                if not text.strip():
                    continue
                if len(text) > self._chunk_size:
                    for sub in self._splitter.split_text(text):
                        chunks.append(Chunk(
                            text=sub, index=idx, source=doc.filename,
                            page=page_no, chunk_type="text",
                        ))
                        idx += 1
                else:
                    chunks.append(Chunk(
                        text=text, index=idx, source=doc.filename,
                        page=page_no, chunk_type="text",
                    ))
                    idx += 1

        if doc.tables:
            for table_data in doc.tables:
                text = table_data.get("text", "")
                if text.strip():
                    chunks.append(Chunk(
                        text=text, index=idx, source=doc.filename,
                        page=table_data.get("page"), chunk_type="table",
                    ))
                    idx += 1

        if not chunks and doc.content:
            for sub in self._splitter.split_text(doc.content):
                chunks.append(Chunk(
                    text=sub, index=idx, source=doc.filename,
                    chunk_type="text",
                ))
                idx += 1

        return chunks
