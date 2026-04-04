"""LangChain tool: list available knowledge base sources and connectors."""

from __future__ import annotations

import json

from langchain_core.tools import BaseTool
from pydantic import Field


class ListSourcesTool(BaseTool):
    name: str = "list_sources"
    description: str = (
        "List available knowledge base sources, connectors, and document types. "
        "Use this to understand what data is available before searching. "
        "Input: empty string or any string (ignored)."
    )
    user_id: str | None = Field(default=None, exclude=True)
    jwt_token: str | None = Field(default=None, exclude=True)

    def _run(self, _: str = "") -> str:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(self._arun(_))

    async def _arun(self, _: str = "") -> str:
        from config.settings import get_index_name, clients

        os_client = clients.create_user_opensearch_client(self.jwt_token or "")

        try:
            result = await os_client.search(
                index=get_index_name(),
                body={
                    "size": 0,
                    "aggs": {
                        "data_sources": {"terms": {"field": "filename", "size": 50}},
                        "document_types": {"terms": {"field": "mimetype", "size": 20}},
                        "connector_types": {"terms": {"field": "connector_type", "size": 10}},
                        "owners": {"terms": {"field": "owner", "size": 20}},
                    },
                },
                params={"terminate_after": 0},
            )
            aggs = result.get("aggregations", {})
            summary = {
                "data_sources": [b["key"] for b in aggs.get("data_sources", {}).get("buckets", [])],
                "document_types": [b["key"] for b in aggs.get("document_types", {}).get("buckets", [])],
                "connector_types": [b["key"] for b in aggs.get("connector_types", {}).get("buckets", [])],
                "owners": [b["key"] for b in aggs.get("owners", {}).get("buckets", [])],
            }
            return json.dumps(summary, indent=2)
        except Exception as e:
            return f"Error listing sources: {e}"
