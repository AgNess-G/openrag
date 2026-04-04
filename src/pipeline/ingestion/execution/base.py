"""ExecutionBackend protocol for the composable pipeline."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pipeline.ingestion.pipeline import IngestionPipeline
from pipeline.ingestion.types import FileMetadata


@runtime_checkable
class ExecutionBackend(Protocol):
    async def submit(
        self,
        pipeline: IngestionPipeline,
        file_tasks: list[FileMetadata],
    ) -> str:
        """Submit a batch of files for processing. Returns batch_id."""
        ...

    async def get_progress(self, batch_id: str) -> dict:
        """Return {total, completed, failed, results}."""
        ...

    async def cancel(self, batch_id: str) -> None:
        """Cancel a running batch."""
        ...
