"""Service layer for the composable ingestion pipeline."""

from __future__ import annotations

import hashlib
import mimetypes
import os
import tempfile
import uuid
from typing import TYPE_CHECKING

from utils.logging_config import get_logger

if TYPE_CHECKING:
    from pipeline.config import PipelineConfig

logger = get_logger(__name__)


class PipelineService:
    """Wraps PipelineBuilder + ExecutionBackend for the API layer."""

    def __init__(
        self,
        pipeline_config: PipelineConfig,
        session_manager=None,
        document_service=None,
    ) -> None:
        from pipeline.execution.local_backend import LocalBackend
        from pipeline.pipeline import PipelineBuilder
        from pipeline.registry import get_default_registry

        self._config = pipeline_config
        self._session_manager = session_manager
        self._registry = get_default_registry()
        self._builder = PipelineBuilder(pipeline_config, self._registry)

        if pipeline_config.execution.backend == "redis":
            from pipeline.execution.redis_backend import RedisBackend

            self._backend = RedisBackend(pipeline_config=pipeline_config)
        else:
            self._backend = LocalBackend(
                concurrency=pipeline_config.execution.concurrency
            )

        self._pipeline = None

    def _get_pipeline(self):
        """Lazy-build the pipeline on first use so startup succeeds even
        when provider credentials aren't configured yet."""
        if self._pipeline is None:
            from config.settings import clients
            os_client = getattr(clients, "opensearch", None)
            self._pipeline = self._builder.build(opensearch_client=os_client)
        return self._pipeline

    async def enqueue(
        self,
        files: list,
        user=None,
        config_overrides: dict | None = None,
    ) -> str:
        """Save uploaded files and submit them for pipeline processing."""
        from pipeline.types import FileMetadata

        file_metas: list[FileMetadata] = []
        for upload_file in files:
            content = await upload_file.read()
            safe_name = upload_file.filename.replace(" ", "_").replace("/", "_")
            tmp_path = os.path.join(tempfile.gettempdir(), f"pipeline_{uuid.uuid4().hex}_{safe_name}")
            with open(tmp_path, "wb") as f:
                f.write(content)

            file_hash = hashlib.sha256(content).hexdigest()
            mt, _ = mimetypes.guess_type(safe_name)

            fm = FileMetadata(
                file_path=tmp_path,
                filename=upload_file.filename,
                file_hash=file_hash,
                file_size=len(content),
                mimetype=mt or "application/octet-stream",
                owner_user_id=user.user_id if user else None,
                jwt_token=user.jwt_token if user else None,
                owner_name=getattr(user, "name", None) if user else None,
                owner_email=getattr(user, "email", None) if user else None,
            )
            file_metas.append(fm)

        batch_id = await self._backend.submit(self._get_pipeline(), file_metas)
        logger.info(
            "Pipeline batch submitted",
            batch_id=batch_id,
            file_count=len(file_metas),
        )
        return batch_id

    async def run_files(
        self,
        file_metas: list,
    ) -> str:
        """Submit pre-built FileMetadata objects for pipeline processing."""
        batch_id = await self._backend.submit(self._get_pipeline(), file_metas)
        logger.info(
            "Pipeline batch submitted (run_files)",
            batch_id=batch_id,
            file_count=len(file_metas),
        )
        return batch_id

    def rebuild(self) -> None:
        """Force a pipeline rebuild (e.g. after config/credentials change)."""
        self._pipeline = None

    async def get_status(self, task_id: str) -> dict:
        return await self._backend.get_progress(task_id)

    async def wait_for_batch(self, batch_id: str) -> dict:
        """Block until a submitted batch completes (local or redis backend)."""
        wait = getattr(self._backend, "wait_for_batch", None)
        if not callable(wait):
            raise NotImplementedError(
                "wait_for_batch is not implemented for this execution backend"
            )
        return await wait(batch_id)

    async def cancel(self, task_id: str) -> None:
        await self._backend.cancel(task_id)
