"""
MCP Apps HTTP server - FastMCP with Streamable HTTP transport.
Exposes OpenRAG tools with MCP App UI resources for settings.
"""
import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.resources.types import FunctionResource
from mcp.types import TextContent
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp_apps.auth import McpAuthMiddleware

# URIs for MCP App UI resources (ui:// scheme per MCP Apps spec)
SETTINGS_VIEW_URI = "ui://openrag/settings-app.html"
MODELS_VIEW_URI = "ui://openrag/models-app.html"

# Path to built MCP App HTML files (mcp-apps/dist/ at project root)
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DIST_DIR = _REPO_ROOT / "mcp-apps" / "dist"

MCP_APP_MIME = "text/html;profile=mcp-app"


def _read_html_resource(filename: str) -> str:
    """Read built HTML file; return placeholder if not built yet."""
    path = DIST_DIR / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    return (
        f"<!DOCTYPE html><html><body><p>MCP App not built. Run: cd mcp-apps && npm install && npm run build</p>"
        f"<p>Expected file: {path}</p></body></html>"
    )


def create_mcp_http_app(services: dict):
    """
    Create the FastMCP Streamable HTTP ASGI app and wrap with API key auth.
    Tools call internal OpenRAG services in-process.
    """
    session_manager = services["session_manager"]
    api_key_service = services["api_key_service"]
    models_service = services["models_service"]

    mcp = FastMCP(
        "OpenRAG",
        streamable_http_path="/",  # when mounted at /mcp, request to /mcp/ gets path "/"
        json_response=True,
        stateless_http=True,
    )

    # -------------------------------------------------------------------------
    # Settings tools (with MCP App UI)
    # -------------------------------------------------------------------------

    @mcp.tool(
        name="openrag_get_settings",
        description=(
            "Get the current OpenRAG configuration. Returns LLM provider and model, "
            "embedding provider and model, chunk settings, document processing options "
            "(table structure, OCR, picture descriptions), and system prompt."
        ),
        meta={"ui": {"resourceUri": SETTINGS_VIEW_URI}},
    )
    async def openrag_get_settings() -> list[TextContent]:
        from config.settings import get_openrag_config

        config = get_openrag_config()
        data = {
            "agent": {
                "llm_provider": config.agent.llm_provider,
                "llm_model": config.agent.llm_model,
                "system_prompt": config.agent.system_prompt or "",
            },
            "knowledge": {
                "embedding_provider": config.knowledge.embedding_provider,
                "embedding_model": config.knowledge.embedding_model,
                "chunk_size": config.knowledge.chunk_size,
                "chunk_overlap": config.knowledge.chunk_overlap,
                "table_structure": config.knowledge.table_structure,
                "ocr": config.knowledge.ocr,
                "picture_descriptions": config.knowledge.picture_descriptions,
            },
        }
        return [TextContent(type="text", text=json.dumps(data))]

    @mcp.tool(
        name="openrag_update_settings",
        description=(
            "Update OpenRAG configuration. All parameters are optional; only provided "
            "fields are changed. Use this to set LLM model, embedding model, chunk size/overlap, "
            "system prompt, and document processing options (table structure, OCR, picture descriptions)."
        ),
        meta={"ui": {"resourceUri": SETTINGS_VIEW_URI}},
    )
    async def openrag_update_settings(
        llm_provider: str | None = None,
        llm_model: str | None = None,
        embedding_provider: str | None = None,
        embedding_model: str | None = None,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        system_prompt: str | None = None,
        table_structure: bool | None = None,
        ocr: bool | None = None,
        picture_descriptions: bool | None = None,
    ) -> list[TextContent]:
        from api.settings import update_settings

        body = {}
        if llm_provider is not None:
            body["llm_provider"] = llm_provider
        if llm_model is not None:
            body["llm_model"] = llm_model
        if embedding_provider is not None:
            body["embedding_provider"] = embedding_provider
        if embedding_model is not None:
            body["embedding_model"] = embedding_model
        if chunk_size is not None:
            body["chunk_size"] = chunk_size
        if chunk_overlap is not None:
            body["chunk_overlap"] = chunk_overlap
        if system_prompt is not None:
            body["system_prompt"] = system_prompt
        if table_structure is not None:
            body["table_structure"] = table_structure
        if ocr is not None:
            body["ocr"] = ocr
        if picture_descriptions is not None:
            body["picture_descriptions"] = picture_descriptions

        if not body:
            return [TextContent(type="text", text=json.dumps({"error": "No settings to update. Provide at least one option."}))]

        # Build a minimal request so update_settings can run
        body_bytes = json.dumps(body).encode("utf-8")
        received = []

        async def receive():
            if not received:
                received.append(True)
                return {"type": "http.request", "body": body_bytes, "more_body": False}
            return {"type": "http.disconnect"}

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [],
            "query_string": b"",
        }
        request = Request(scope, receive, lambda _: None)
        response = await update_settings(request, session_manager)
        content = response.body.decode("utf-8")
        return [TextContent(type="text", text=content)]

    @mcp.tool(
        name="openrag_list_models",
        description=(
            "List available language models and embedding models for a provider. "
            "Use this before updating settings to see which model values are valid. "
            "Provider must be configured in OpenRAG (API key or endpoint set in Settings)."
        ),
        meta={"ui": {"resourceUri": MODELS_VIEW_URI}},
    )
    async def openrag_list_models(provider: str) -> list[TextContent]:
        from config.settings import get_openrag_config
        from api.v1.models import _fetch_models, VALID_PROVIDERS

        provider = (provider or "").lower()
        if provider not in VALID_PROVIDERS:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {"error": f"Invalid provider. Must be one of: {', '.join(sorted(VALID_PROVIDERS))}"}
                    ),
                )
            ]
        try:
            config = get_openrag_config()
            models, error_response = await _fetch_models(provider, config, models_service)
            if error_response is not None:
                body = error_response.body
                return [TextContent(type="text", text=body.decode("utf-8"))]
            return [TextContent(type="text", text=json.dumps(models))]
        except Exception as e:
            from utils.logging_config import get_logger
            get_logger(__name__).error("List models error: %s", e)
            return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

    # -------------------------------------------------------------------------
    # UI resources (serve built HTML)
    # -------------------------------------------------------------------------

    def _settings_html() -> str:
        return _read_html_resource("settings-app.html")

    def _models_html() -> str:
        return _read_html_resource("models-app.html")

    mcp.add_resource(
        FunctionResource.from_function(
            _settings_html,
            uri=SETTINGS_VIEW_URI,
            name="settings-app",
            mime_type=MCP_APP_MIME,
            meta={"ui": {"csp": {"resourceDomains": ["https://fonts.googleapis.com", "https://fonts.gstatic.com", "https://unpkg.com"]}}},
        )
    )
    mcp.add_resource(
        FunctionResource.from_function(
            _models_html,
            uri=MODELS_VIEW_URI,
            name="models-app",
            mime_type=MCP_APP_MIME,
            meta={"ui": {"csp": {"resourceDomains": ["https://fonts.googleapis.com", "https://fonts.gstatic.com", "https://unpkg.com"]}}},
        )
    )

    # -------------------------------------------------------------------------
    # Build ASGI app and wrap with auth + CORS
    # -------------------------------------------------------------------------
    app = mcp.streamable_http_app()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app = McpAuthMiddleware(app, api_key_service)
    return app
