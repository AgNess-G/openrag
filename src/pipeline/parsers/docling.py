"""Docling-serve based document parser."""

from __future__ import annotations

import os

import httpx

from pipeline.types import FileMetadata, ParsedDocument


class DoclingParser:
    """Parse documents via docling-serve HTTP API."""

    def __init__(
        self,
        httpx_client: httpx.AsyncClient | None = None,
        service_url: str | None = None,
        ocr: bool = False,
        ocr_engine: str = "easyocr",
        table_structure: bool = True,
    ) -> None:
        self._client = httpx_client
        self._owns_client = httpx_client is None
        self._service_url = service_url or os.getenv(
            "DOCLING_SERVICE_URL", "http://localhost:5001"
        )
        self._ocr = ocr
        self._ocr_engine = ocr_engine
        self._table_structure = table_structure

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=300.0)
        return self._client

    async def parse(self, file_path: str, metadata: FileMetadata) -> ParsedDocument:
        from pathlib import Path

        from utils.document_processing import extract_relevant

        client = await self._get_client()
        path = Path(file_path)
        file_bytes = path.read_bytes()

        data: dict[str, str] = {"to_formats": "json"}
        if self._ocr:
            data["do_ocr"] = "true"
            data["ocr_engine"] = self._ocr_engine
        else:
            data["do_ocr"] = "false"

        url = f"{self._service_url}/v1/convert/file"
        response = await client.post(
            url,
            files={"files": (path.name, file_bytes)},
            data=data,
        )
        response.raise_for_status()
        resp_json = response.json()

        doc_content = resp_json.get("document", {}).get("json_content")
        if doc_content is None:
            raise RuntimeError("docling-serve response missing document.json_content")

        slim_doc = extract_relevant(doc_content)
        chunks = slim_doc.get("chunks", [])
        content = "\n\n".join(c.get("text", "") for c in chunks)
        pages = [c for c in chunks if c.get("type") == "text"]
        tables = [c for c in chunks if c.get("type") == "table"]

        return ParsedDocument(
            filename=metadata.filename,
            content=content,
            mimetype=metadata.mimetype or slim_doc.get("mimetype", "application/octet-stream"),
            pages=pages or None,
            tables=tables or None,
            metadata={"docling_id": slim_doc.get("id")},
        )
