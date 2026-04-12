from __future__ import annotations

from typing import Any, Dict

from auth_context import get_auth_context
from config.settings import (
    EMBED_MODEL,
    WATSONX_EMBEDDING_DIMENSIONS,
    clients,
    get_embedding_model,
)
from services.knowledge_access import build_access_context
from services.knowledge_backend import get_knowledge_backend_service
from utils.logging_config import get_logger

logger = get_logger(__name__)

MAX_EMBED_RETRIES = 3
EMBED_RETRY_INITIAL_DELAY = 1.0
EMBED_RETRY_MAX_DELAY = 8.0


class SearchService:
    def __init__(self, session_manager=None):
        self.session_manager = session_manager
        self.knowledge_backend = get_knowledge_backend_service(session_manager)

    @staticmethod
    def _format_embedding_model_for_client(model_name: str) -> str:
        if any(
            model_name.startswith(prefix + "/")
            for prefix in ["openai", "ollama", "watsonx", "anthropic"]
        ):
            return model_name
        if ":" in model_name:
            return f"ollama/{model_name}"
        if model_name in WATSONX_EMBEDDING_DIMENSIONS:
            return f"watsonx/{model_name}"
        return model_name

    async def _generate_query_embedding(self, query: str, model_name: str) -> list[float]:
        import asyncio

        formatted_model = self._format_embedding_model_for_client(model_name)
        delay = EMBED_RETRY_INITIAL_DELAY
        last_exception = None

        for attempt in range(1, MAX_EMBED_RETRIES + 1):
            try:
                response = await clients.patched_embedding_client.embeddings.create(
                    model=formatted_model,
                    input=[query],
                )
                embedding = getattr(response.data[0], "embedding", None)
                if embedding is None:
                    embedding = response.data[0]["embedding"]
                return embedding
            except Exception as exc:
                last_exception = exc
                if attempt == MAX_EMBED_RETRIES:
                    logger.error(
                        "Failed to embed query after retries",
                        model=model_name,
                        attempts=attempt,
                        error=str(exc),
                    )
                    raise RuntimeError(
                        f"Failed to embed query with model {model_name}"
                    ) from exc

                logger.warning(
                    "Retrying query embedding generation",
                    model=model_name,
                    attempt=attempt,
                    max_attempts=MAX_EMBED_RETRIES,
                    error=str(exc),
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, EMBED_RETRY_MAX_DELAY)

        raise RuntimeError(
            f"Failed to embed query with model {model_name}"
        ) from last_exception

    def _build_access_context(
        self,
        *,
        user_id: str | None = None,
        jwt_token: str | None = None,
        user_email: str | None = None,
    ):
        resolved_user_id = user_id
        resolved_jwt_token = jwt_token
        if resolved_user_id is None and resolved_jwt_token is None:
            resolved_user_id, resolved_jwt_token = get_auth_context()

        return build_access_context(
            user_id=resolved_user_id,
            user_email=user_email,
            jwt_token=resolved_jwt_token,
            session_manager=self.session_manager,
        )

    async def search_tool(self, query: str, embedding_model: str = None) -> Dict[str, Any]:
        from auth_context import get_score_threshold, get_search_filters, get_search_limit

        filters = get_search_filters() or {}
        limit = get_search_limit()
        score_threshold = get_score_threshold()
        resolved_embedding_model = embedding_model or get_embedding_model() or EMBED_MODEL
        access_context = self._build_access_context()
        if access_context.enforce_acl and not access_context.principals:
            return {"results": [], "error": "Authentication required"}

        return await self.knowledge_backend.search(
            query=query,
            embedding_model=resolved_embedding_model,
            filters=filters,
            limit=limit,
            score_threshold=score_threshold,
            access_context=access_context,
            embed_query=self._generate_query_embedding,
        )

    async def search(
        self,
        query: str,
        user_id: str = None,
        jwt_token: str = None,
        filters: Dict[str, Any] = None,
        limit: int = 10,
        score_threshold: float = 0,
        embedding_model: str = None,
        user_email: str = None,
    ) -> Dict[str, Any]:
        from auth_context import set_auth_context, set_search_filters, set_search_limit, set_score_threshold

        if user_id:
            set_auth_context(user_id, jwt_token)

        set_search_filters(filters or {})

        set_search_limit(limit)
        set_score_threshold(score_threshold)

        access_context = self._build_access_context(
            user_id=user_id,
            jwt_token=jwt_token,
            user_email=user_email,
        )
        if access_context.enforce_acl and not access_context.principals:
            return {"results": [], "error": "Authentication required"}

        resolved_embedding_model = embedding_model or get_embedding_model() or EMBED_MODEL
        return await self.knowledge_backend.search(
            query=query,
            embedding_model=resolved_embedding_model,
            filters=filters or {},
            limit=limit,
            score_threshold=score_threshold,
            access_context=access_context,
            embed_query=self._generate_query_embedding,
        )
