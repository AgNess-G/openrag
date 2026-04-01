"""Local asyncio-based execution backend."""

from __future__ import annotations

import asyncio
import uuid

from pipeline.pipeline import IngestionPipeline
from pipeline.types import FileMetadata, PipelineResult
from utils.logging_config import get_logger

logger = get_logger(__name__)


class LocalBackend:
    """In-process execution using asyncio.Semaphore for concurrency control."""

    def __init__(self, concurrency: int = 4) -> None:
        self._semaphore = asyncio.Semaphore(concurrency)
        self._batches: dict[str, _BatchState] = {}

    async def submit(
        self,
        pipeline: IngestionPipeline,
        file_tasks: list[FileMetadata],
    ) -> str:
        batch_id = str(uuid.uuid4())
        state = _BatchState(total=len(file_tasks))
        self._batches[batch_id] = state

        names = [fm.filename or fm.file_path for fm in file_tasks]
        logger.info(
            "Composable pipeline batch submitted (local backend)",
            batch_id=batch_id,
            file_count=len(file_tasks),
            files=names,
        )

        for fm in file_tasks:
            task = asyncio.create_task(
                self._run_one(batch_id, pipeline, fm, state)
            )
            state.tasks.append(task)

        state.monitor_task = asyncio.create_task(
            self._log_batch_when_done(batch_id, list(state.tasks), state)
        )

        return batch_id

    async def wait_for_batch(self, batch_id: str) -> dict:
        """Block until all files in the batch have finished processing."""
        state = self._batches.get(batch_id)
        if state is None:
            raise KeyError(f"Unknown batch: {batch_id}")
        if state.tasks:
            await asyncio.gather(*state.tasks, return_exceptions=True)
        return await self.get_progress(batch_id)

    async def _log_batch_when_done(
        self,
        batch_id: str,
        tasks: list[asyncio.Task],
        state: _BatchState,
    ) -> None:
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        for i, out in enumerate(outcomes):
            if isinstance(out, BaseException):
                logger.error(
                    "Composable pipeline: worker task raised",
                    batch_id=batch_id,
                    task_index=i,
                    error=str(out),
                    error_type=type(out).__name__,
                )
        logger.info(
            "Composable pipeline batch finished",
            batch_id=batch_id,
            total=state.total,
            completed=state.completed,
            failed=state.failed,
        )

    async def get_progress(self, batch_id: str) -> dict:
        state = self._batches.get(batch_id)
        if state is None:
            raise KeyError(f"Unknown batch: {batch_id}")
        return {
            "total": state.total,
            "completed": state.completed,
            "failed": state.failed,
            "in_flight": sorted(state.in_flight),
            "results": list(state.results),
        }

    async def cancel(self, batch_id: str) -> None:
        state = self._batches.get(batch_id)
        if state is None:
            return
        for task in state.tasks:
            if not task.done():
                task.cancel()

    async def _run_one(
        self,
        batch_id: str,
        pipeline: IngestionPipeline,
        metadata: FileMetadata,
        state: _BatchState,
    ) -> PipelineResult:
        label = metadata.filename or metadata.file_path
        logger.info(
            "Composable pipeline: waiting for slot (concurrency limit)",
            batch_id=batch_id,
            file=label,
            mimetype=metadata.mimetype,
        )
        async with self._semaphore:
            state.in_flight.add(label)
            logger.info(
                "Composable pipeline: processing file",
                batch_id=batch_id,
                file=label,
                file_path=metadata.file_path,
                connector_type=metadata.connector_type,
            )
            try:
                result = await pipeline.run(metadata.file_path, metadata)
            finally:
                state.in_flight.discard(label)

            if result.status == "failed":
                state.failed += 1
                logger.error(
                    "Composable pipeline: file failed",
                    batch_id=batch_id,
                    file=label,
                    error=result.error,
                    duration_seconds=round(result.duration_seconds, 2),
                )
            elif result.status == "skipped":
                state.completed += 1
                logger.warning(
                    "Composable pipeline: file skipped",
                    batch_id=batch_id,
                    file=label,
                    reason=result.error,
                    duration_seconds=round(result.duration_seconds, 2),
                )
            else:
                state.completed += 1
                logger.info(
                    "Composable pipeline: file finished",
                    batch_id=batch_id,
                    file=label,
                    status=result.status,
                    chunks_indexed=result.chunks_indexed,
                    chunks_total=result.chunks_total,
                    duration_seconds=round(result.duration_seconds, 2),
                )
            state.results.append(result)
            return result


class _BatchState:
    __slots__ = (
        "total",
        "completed",
        "failed",
        "results",
        "tasks",
        "in_flight",
        "monitor_task",
    )

    def __init__(self, total: int) -> None:
        self.total = total
        self.completed = 0
        self.failed = 0
        self.results: list[PipelineResult] = []
        self.tasks: list[asyncio.Task] = []
        self.in_flight: set[str] = set()
        self.monitor_task: asyncio.Task | None = None
