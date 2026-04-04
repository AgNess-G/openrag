"""Local cross-encoder reranker using sentence-transformers."""

from __future__ import annotations

from pipeline.retrieval.types import SearchResult
from utils.logging_config import get_logger

logger = get_logger(__name__)

try:
    from sentence_transformers import CrossEncoder as _CrossEncoder

    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


class CrossEncoderReranker:
    def __init__(
        self,
        model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        top_k: int = 10,
    ) -> None:
        if not _AVAILABLE:
            raise ImportError(
                "sentence-transformers is not installed. "
                "Install it with: pip install 'openrag[huggingface]'"
            )
        self._model = _CrossEncoder(model)
        self.top_k = top_k

    async def rerank(self, query: str, results: list[SearchResult]) -> list[SearchResult]:
        if not results:
            return results

        import asyncio

        pairs = [(query, r.text) for r in results]
        # CrossEncoder is synchronous — run in executor to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        scores = await loop.run_in_executor(None, self._model.predict, pairs)

        scored = sorted(zip(scores, results), key=lambda x: x[0], reverse=True)
        reranked = []
        for score, result in scored[: self.top_k]:
            reranked.append(SearchResult(
                text=result.text,
                filename=result.filename,
                score=float(score),
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
            "CrossEncoderReranker: reranked",
            input_count=len(results),
            output_count=len(reranked),
        )
        return reranked
