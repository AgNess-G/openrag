"""Core pipeline orchestration and builder."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from pipeline.types import FileMetadata, PipelineResult
from utils.logging_config import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:
    from pipeline.chunkers.base import Chunker
    from pipeline.config import PipelineConfig
    from pipeline.embedders.base import Embedder
    from pipeline.indexers.base import Indexer
    from pipeline.parsers.base import DocumentParser
    from pipeline.preprocessors.base import Preprocessor
    from pipeline.registry import ComponentRegistry


class IngestionPipeline:
    """Runs the full parse -> preprocess -> chunk -> embed -> index flow."""

    def __init__(
        self,
        parser: DocumentParser,
        preprocessors: list[Preprocessor],
        chunker: Chunker,
        embedder: Embedder,
        indexer: Indexer,
    ) -> None:
        self.parser = parser
        self.preprocessors = preprocessors
        self.chunker = chunker
        self.embedder = embedder
        self.indexer = indexer

    async def run(self, file_path: str, metadata: FileMetadata) -> PipelineResult:
        start = time.monotonic()
        label = metadata.filename or file_path

        def _elapsed() -> float:
            return round(time.monotonic() - start, 2)

        try:
            logger.info(
                "Pipeline stage: parse",
                file=label,
                parser=type(self.parser).__name__,
            )
            doc = await self.parser.parse(file_path, metadata)
            actual_parser = getattr(self.parser, "last_used", None) or type(self.parser).__name__
            logger.info(
                "Pipeline stage: parse done",
                file=label,
                parser_used=actual_parser,
                content_chars=len(doc.content or ""),
                elapsed_s=_elapsed(),
            )

            for i, pp in enumerate(self.preprocessors):
                logger.info(
                    "Pipeline stage: preprocess",
                    file=label,
                    preprocessor=type(pp).__name__,
                    index=i,
                )
                doc = await pp.process(doc)

            logger.info(
                "Pipeline stage: chunk",
                file=label,
                chunker=type(self.chunker).__name__,
                chunk_size=getattr(self.chunker, "chunk_size", None),
                chunk_overlap=getattr(self.chunker, "chunk_overlap", None),
            )
            chunks = await self.chunker.chunk(doc)
            if not chunks:
                logger.warning(
                    "Pipeline stage: no chunks produced",
                    file=label,
                    elapsed_s=_elapsed(),
                )
                return PipelineResult(
                    file_path=file_path,
                    document_id=metadata.file_hash,
                    filename=metadata.filename,
                    chunks_total=0,
                    chunks_indexed=0,
                    status="skipped",
                    error="No chunks produced",
                    duration_seconds=time.monotonic() - start,
                )

            logger.info(
                "Pipeline stage: embed",
                file=label,
                chunk_count=len(chunks),
                embedder=type(self.embedder).__name__,
            )
            embedded = await self.embedder.embed(chunks)
            logger.info(
                "Pipeline stage: embed done",
                file=label,
                embedded_count=len(embedded),
                elapsed_s=_elapsed(),
            )

            logger.info(
                "Pipeline stage: index",
                file=label,
                indexer=type(self.indexer).__name__,
            )
            result = await self.indexer.index(embedded, metadata)
            logger.info(
                "Pipeline stage: index done",
                file=label,
                chunks_indexed=result.chunks_indexed,
                index_name=result.index_name,
                elapsed_s=_elapsed(),
            )

            return PipelineResult(
                file_path=file_path,
                document_id=result.document_id,
                filename=metadata.filename,
                chunks_total=len(chunks),
                chunks_indexed=result.chunks_indexed,
                status="success",
                duration_seconds=time.monotonic() - start,
            )
        except Exception as exc:
            logger.error(
                "Pipeline stage: exception",
                file=label,
                error=str(exc),
                error_type=type(exc).__name__,
                elapsed_s=_elapsed(),
            )
            return PipelineResult(
                file_path=file_path,
                document_id=metadata.file_hash,
                filename=metadata.filename,
                chunks_total=0,
                chunks_indexed=0,
                status="failed",
                error=str(exc),
                duration_seconds=time.monotonic() - start,
            )


class PipelineBuilder:
    """Construct an IngestionPipeline from config + registry."""

    def __init__(self, config: PipelineConfig, registry: ComponentRegistry) -> None:
        self._config = config
        self._registry = registry

    def build(self, opensearch_client=None) -> IngestionPipeline:
        parser = self._build_parser()
        preprocessors = self._build_preprocessors(opensearch_client)
        chunker = self._build_chunker()
        embedder = self._build_embedder()
        indexer = self._build_indexer(opensearch_client)
        return IngestionPipeline(parser, preprocessors, chunker, embedder, indexer)

    def _build_parser(self):
        cfg = self._config.parser
        cls = self._registry.get(cfg.type.value, "parser")

        if cfg.type.value == "docling":
            kwargs: dict = {
                "ocr": cfg.docling.ocr,
                "ocr_engine": cfg.docling.ocr_engine,
                "table_structure": cfg.docling.table_structure,
            }
            if cfg.docling.serve_url:
                kwargs["service_url"] = cfg.docling.serve_url
            return cls(**kwargs)
        return cls()

    def _build_preprocessors(self, opensearch_client=None) -> list:
        pps = []
        for pp_cfg in self._config.preprocessors:
            cls = self._registry.get(pp_cfg.type, "preprocessor")
            extra = {k: v for k, v in pp_cfg.model_dump().items() if k != "type"}
            if pp_cfg.type == "dedup" and opensearch_client:
                extra["opensearch_client"] = opensearch_client
            pps.append(cls(**extra))
        return pps

    def _build_chunker(self):
        cfg = self._config.chunker
        cls = self._registry.get(cfg.type.value, "chunker")
        kwargs: dict = {}
        if cfg.type.value in ("recursive", "character", "docling_hybrid"):
            kwargs["chunk_size"] = cfg.chunk_size
            kwargs["chunk_overlap"] = cfg.chunk_overlap
        if cfg.type.value == "recursive":
            kwargs["separators"] = cfg.separators
        if cfg.type.value == "character":
            kwargs["separator"] = cfg.separators[0] if cfg.separators else "\n\n"
        if cfg.type.value == "docling_hybrid":
            kwargs["max_tokens"] = cfg.max_tokens
        return cls(**kwargs)

    def _build_embedder(self):
        cfg = self._config.embedder
        cls = self._registry.get(cfg.provider, "embedder")
        kwargs = {"model": cfg.model, "batch_size": cfg.batch_size}
        if cfg.provider in ("openai", "watsonx"):
            kwargs["max_tokens"] = cfg.max_tokens
        return cls(**kwargs)

    def _build_indexer(self, opensearch_client=None):
        cfg = self._config.indexer
        cls = self._registry.get(cfg.type, "indexer")
        return cls(
            opensearch_client=opensearch_client,
            bulk_batch_size=cfg.bulk_batch_size,
            retry_attempts=cfg.retry_attempts,
            retry_backoff=cfg.retry_backoff,
        )
