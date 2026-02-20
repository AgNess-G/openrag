"""
Public API v1 Settings endpoint.

Provides access to configuration settings.
Uses API key authentication.
"""
from typing import Optional

from fastapi import Depends
from pydantic import BaseModel
from starlette.responses import JSONResponse
from utils.logging_config import get_logger
from config.settings import get_openrag_config
from dependencies import get_api_key_user_async
from session_manager import User

logger = get_logger(__name__)


class SettingsUpdateBody(BaseModel):
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None


async def get_settings_endpoint(
    user: User = Depends(get_api_key_user_async),
):
    """Get current OpenRAG configuration (read-only). GET /v1/settings"""
    try:
        config = get_openrag_config()
        settings = {
            "agent": {
                "llm_provider": config.agent.llm_provider,
                "llm_model": config.agent.llm_model,
                "system_prompt": config.agent.system_prompt,
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
        return JSONResponse(settings)
    except Exception as e:
        logger.error("Failed to get settings", error=str(e))
        return JSONResponse({"error": "Failed to get settings"}, status_code=500)


async def update_settings_endpoint(
    body: SettingsUpdateBody,
    user: User = Depends(get_api_key_user_async),
):
    """Update OpenRAG configuration settings. POST /v1/settings"""
    from api.settings import update_settings
    return await update_settings(body=body)
