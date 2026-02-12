"""
ASGI middleware for MCP HTTP endpoint authentication using ORAG API keys.
"""
from starlette.responses import JSONResponse

from config.settings import is_no_auth_mode
from utils.logging_config import get_logger

logger = get_logger(__name__)


def _extract_api_key_from_scope(scope: dict) -> str | None:
    """
    Extract API key from ASGI scope headers.

    Supports:
    - X-API-Key header
    - Authorization: Bearer orag_... header
    """
    headers = scope.get("headers") or []
    # Headers are list of (b"lowercase-key", b"value") in ASGI
    header_dict = {}
    for name, value in headers:
        key = name.decode("latin-1").lower()
        header_dict[key] = value.decode("latin-1")

    api_key = header_dict.get("x-api-key")
    if api_key and api_key.startswith("orag_"):
        return api_key

    auth_header = header_dict.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if token.startswith("orag_"):
            return token

    return None


class McpAuthMiddleware:
    """
    ASGI middleware that validates ORAG API key before forwarding to the MCP app.
    Returns 401 JSON if the key is missing or invalid.
    """

    def __init__(self, app, api_key_service):
        self.app = app
        self.api_key_service = api_key_service

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Skip authentication if in no-auth mode (OAuth not configured)
        if is_no_auth_mode():
            logger.debug("MCP auth bypassed: running in no-auth mode")
            await self.app(scope, receive, send)
            return

        api_key = _extract_api_key_from_scope(scope)
        if not api_key:
            response = JSONResponse(
                {
                    "error": "API key required",
                    "message": "Provide API key via X-API-Key header or Authorization: Bearer header",
                },
                status_code=401,
            )
            await response(scope, receive, send)
            return

        user_info = await self.api_key_service.validate_key(api_key)
        if not user_info:
            response = JSONResponse(
                {
                    "error": "Invalid API key",
                    "message": "The provided API key is invalid or has been revoked",
                },
                status_code=401,
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
