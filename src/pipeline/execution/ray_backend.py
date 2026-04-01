"""Ray-based distributed execution backend."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from pipeline.types import FileMetadata, PipelineResult

if TYPE_CHECKING:
    from pipeline.config import RayConfig
    from pipeline.pipeline import IngestionPipeline

try:
    import ray

    _RAY_AVAILABLE = True
except ImportError:
    _RAY_AVAILABLE = False


class RayBackend:
    """Distributed execution using Ray remote tasks."""

    def __init__(self, config: RayConfig | None = None) -> None:
        if not _RAY_AVAILABLE:
            raise ImportError(
                "Ray is not installed. Install with: pip install 'openrag[ray]'"
            )
        self._config = config
        self._batches: dict[str, _RayBatchState] = {}

    def _ensure_initialized(self) -> None:
        if not ray.is_initialized():
            address = self._config.address if self._config else "auto"
            ray.init(address=address, ignore_reinit_error=True)

    async def submit(
        self,
        pipeline: IngestionPipeline,
        file_tasks: list[FileMetadata],
    ) -> str:
        self._ensure_initialized()

        num_cpus = self._config.num_cpus_per_task if self._config else 1
        num_gpus = self._config.num_gpus_per_task if self._config else 0
        max_retries = self._config.max_retries if self._config else 3

        @ray.remote(num_cpus=num_cpus, num_gpus=num_gpus, max_retries=max_retries)
        def _run_pipeline(pipe, file_path, metadata):
            import asyncio
            return asyncio.get_event_loop().run_until_complete(
                pipe.run(file_path, metadata)
            )

        batch_id = str(uuid.uuid4())
        refs = []
        for fm in file_tasks:
            ref = _run_pipeline.remote(pipeline, fm.file_path, fm)
            refs.append(ref)

        self._batches[batch_id] = _RayBatchState(
            total=len(file_tasks), refs=refs
        )
        return batch_id

    async def get_progress(self, batch_id: str) -> dict:
        state = self._batches.get(batch_id)
        if state is None:
            raise KeyError(f"Unknown batch: {batch_id}")

        completed_results: list[PipelineResult] = []
        still_pending = []

        for ref in state.refs:
            ready, _ = ray.wait([ref], timeout=0)
            if ready:
                try:
                    result = ray.get(ready[0])
                    completed_results.append(result)
                except Exception as exc:
                    completed_results.append(
                        PipelineResult(
                            file_path="unknown",
                            document_id="",
                            filename="",
                            chunks_total=0,
                            chunks_indexed=0,
                            status="failed",
                            error=str(exc),
                        )
                    )
            else:
                still_pending.append(ref)

        state.refs = still_pending
        failed = sum(1 for r in completed_results if r.status == "failed")
        return {
            "total": state.total,
            "completed": len(completed_results) - failed,
            "failed": failed,
            "results": completed_results,
        }

    async def cancel(self, batch_id: str) -> None:
        state = self._batches.get(batch_id)
        if state is None:
            return
        for ref in state.refs:
            ray.cancel(ref, force=True)
        state.refs.clear()


class _RayBatchState:
    __slots__ = ("total", "refs")

    def __init__(self, total: int, refs: list) -> None:
        self.total = total
        self.refs = refs
