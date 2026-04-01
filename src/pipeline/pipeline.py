"""Core pipeline orchestration and builder."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from pipeline.types import FileMetadata, PipelineResult

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
        try:
            doc = await self.parser.parse(file_path, metadata)

            for pp in self.preprocessors:
                doc = await pp.process(doc)

            chunks = await self.chunker.chunk(doc)
            if not chunks:
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

            embedded = await self.embedder.embed(chunks)
            result = await self.indexer.index(embedded, metadata)

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
