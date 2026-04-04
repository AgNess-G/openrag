"""Cohere Rerank API reranker."""

from __future__ import annotations

import os

from pipeline.retrieval.types import SearchResult
from utils.logging_config import get_logger

logger = get_logger(__name__)

try:
    import cohere as _cohere

    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


class CohereReranker:
    def __init__(self, model: str = "rerank-english-v3.0", top_k: int = 10) -> None:
        if not _AVAILABLE:
            raise ImportError(
                "cohere is not installed. Install it with: pip install 'cohere>=5.0'"
            )
        api_key = os.getenv("COHERE_API_KEY")
        if not api_key:
            raise ValueError("COHERE_API_KEY environment variable is required for Cohere reranker")
        self._client = _cohere.AsyncClient(api_key=api_key)
        self.model = model
        self.top_k = top_k

    async def rerank(self, query: str, results: list[SearchResult]) -> list[SearchResult]:
        if not results:
            return results

        documents = [r.text for r in results]
        response = await self._client.rerank(
            model=self.model,
            query=query,
            documents=documents,
            top_n=min(self.top_k, len(results)),
        )

        reranked = []
        for item in response.results:
            result = results[item.index]
            # Update score with Cohere relevance score
            reranked.append(SearchResult(
                text=result.text,
                filename=result.filename,
                score=item.relevance_score,
                page=result.page,
                mimetype=result.mimetype,
                source_url=result.source_url,
                owner=result.owner,
                owner_name=result.owner_name,
                owner_email=result.owner_email,
                connector_type=result.connector_type,
                document_id=result.document_id,
                metadata=result.metadata,
            ))

        logger.info(
            "CohereReranker: reranked",
            input_count=len(results),
            output_count=len(reranked),
            model=self.model,
        )
        return reranked
