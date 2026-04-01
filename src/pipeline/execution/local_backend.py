"""Local asyncio-based execution backend."""

from __future__ import annotations

import asyncio
import uuid

from pipeline.pipeline import IngestionPipeline
from pipeline.types import FileMetadata, PipelineResult


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

        for fm in file_tasks:
            task = asyncio.create_task(self._run_one(pipeline, fm, state))
            state.tasks.append(task)

        return batch_id

    async def get_progress(self, batch_id: str) -> dict:
        state = self._batches.get(batch_id)
        if state is None:
            raise KeyError(f"Unknown batch: {batch_id}")
        return {
            "total": state.total,
            "completed": state.completed,
            "failed": state.failed,
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
        pipeline: IngestionPipeline,
        metadata: FileMetadata,
        state: _BatchState,
    ) -> PipelineResult:
        async with self._semaphore:
            result = await pipeline.run(metadata.file_path, metadata)
            if result.status == "failed":
                state.failed += 1
            else:
                state.completed += 1
            state.results.append(result)
            return result


class _BatchState:
    __slots__ = ("total", "completed", "failed", "results", "tasks")

    def __init__(self, total: int) -> None:
        self.total = total
        self.completed = 0
        self.failed = 0
        self.results: list[PipelineResult] = []
        self.tasks: list[asyncio.Task] = []
