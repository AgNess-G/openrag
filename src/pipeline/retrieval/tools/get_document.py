"""LangChain tool: fetch full document text by document ID."""

from __future__ import annotations

from langchain_core.tools import BaseTool
from pydantic import Field


class GetDocumentTool(BaseTool):
    name: str = "get_document"
    description: str = (
        "Fetch the full text of a specific document by its document_id. "
        "Use this to drill into a source found by a previous search tool. "
        "Input: document_id string."
    )
    user_id: str | None = Field(default=None, exclude=True)
    jwt_token: str | None = Field(default=None, exclude=True)

    def _run(self, document_id: str) -> str:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(self._arun(document_id))

    async def _arun(self, document_id: str) -> str:
        from config.settings import get_index_name, clients

        os_client = clients.create_user_opensearch_client(self.jwt_token or "")

        try:
            result = await os_client.get(index=get_index_name(), id=document_id)
            src = result.get("_source", {})
            text = src.get("text", "")
            filename = src.get("filename", document_id)
            return f"Document: {filename}\n\n{text}"
        except Exception as e:
            return f"Document not found: {document_id}. Error: {e}"
