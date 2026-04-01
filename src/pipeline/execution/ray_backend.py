"""Ray-based distributed execution backend."""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import asdict
from typing import TYPE_CHECKING

from pipeline.types import FileMetadata, PipelineResult

if TYPE_CHECKING:
    from pipeline.config import PipelineConfig
    from pipeline.pipeline import IngestionPipeline

try:
    import ray

    _RAY_AVAILABLE = True
except ImportError:
    _RAY_AVAILABLE = False


def _ray_worker_env_vars() -> dict[str, str]:
    """Forward driver env into Ray workers (isolated job venvs do not inherit the shell).

    Only ``env_vars`` is used — not ``pip``/``uv`` runtime_env keys — so this stays
    compatible with ``uv run``. Values must be strings for Ray.
    """
    prefixes = (
        "OPENAI_",
        "AZURE_OPENAI_",
        "OPENSEARCH_",
        "WATSONX_",
        "OLLAMA_",
        "PIPELINE_",
        "DOCLING_",
        "LANGFLOW_",
        "IBM_",
        "AWS_",
        "GOOGLE_",
        "HF_",
        "HUGGINGFACE",
        "VOYAGE_",
        "COHERE_",
        "ANTHROPIC_",
    )
    exact = {
        "NO_PROXY",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "SSL_CERT_FILE",
        "REQUESTS_CA_BUNDLE",
        "GOOGLE_APPLICATION_CREDENTIALS",
    }
    out: dict[str, str] = {}
    for key, value in os.environ.items():
        if not value:
            continue
        if key in exact or any(key.startswith(p) for p in prefixes):
            out[key] = value

    # Onboarding often persists keys in OpenRAG config but not in os.environ; workers only
    # see what we pass via runtime_env.
    try:
        from config.settings import get_openrag_config

        cfg = get_openrag_config()
        oa = getattr(cfg.providers, "openai", None)
        if oa and getattr(oa, "api_key", None) and "OPENAI_API_KEY" not in out:
            out["OPENAI_API_KEY"] = str(oa.api_key)
        wx = getattr(cfg.providers, "watsonx", None)
        if wx:
            if getattr(wx, "api_key", None) and "WATSONX_API_KEY" not in out:
                out["WATSONX_API_KEY"] = str(wx.api_key)
            if getattr(wx, "project_id", None) and "WATSONX_PROJECT_ID" not in out:
                out["WATSONX_PROJECT_ID"] = str(wx.project_id)
            if getattr(wx, "endpoint", None) and "WATSONX_ENDPOINT" not in out:
                out["WATSONX_ENDPOINT"] = str(wx.endpoint)
    except Exception:
        pass

    return out


def _execute_pipeline_file_on_worker(
    config_dict: dict,
    file_path: str,
    metadata_dict: dict,
) -> PipelineResult:
    """Runs in a Ray worker process. Rebuilds the pipeline from config so drivers
    never pickle HTTP clients, locks, or other non-serializable objects."""
    import asyncio

    from config.settings import clients
    from pipeline.config import PipelineConfig
    from pipeline.pipeline import PipelineBuilder
    from pipeline.registry import get_default_registry
    from pipeline.types import FileMetadata

    async def _run() -> PipelineResult:
        # Ray reuses worker processes across tasks. Each call to asyncio.run() creates
        # a new event loop and closes it when done. Any aiohttp client (AsyncOpenSearch
        # / AIOHttpConnection) is bound to the event loop in which it was created, so
        # reusing a client across asyncio.run() calls causes
        # "RuntimeError: Event loop is closed". Close and reinitialize on every call.
        if clients.opensearch is not None:
            try:
                await clients.opensearch.close()
            except Exception:
                pass
            clients.opensearch = None
        await clients.initialize()

        cfg = PipelineConfig.model_validate(config_dict)
        fm = FileMetadata(**metadata_dict)
        builder = PipelineBuilder(cfg, get_default_registry())
        pipe = builder.build(opensearch_client=clients.opensearch)
        try:
            return await pipe.run(file_path, fm)
        finally:
            # Close the client before asyncio.run() tears down the loop so
            # aiohttp does not log "Unclosed client session" warnings.
            try:
                await clients.opensearch.close()
            except Exception:
                pass
            clients.opensearch = None

    return asyncio.run(_run())


if _RAY_AVAILABLE:
    _execute_pipeline_file_remote = ray.remote(_execute_pipeline_file_on_worker)
else:
    _execute_pipeline_file_remote = None  # type: ignore[misc, assignment]


class RayBackend:
    """Distributed execution using Ray remote tasks."""

    def __init__(self, pipeline_config: PipelineConfig) -> None:
        if not _RAY_AVAILABLE:
            raise ImportError(
                "Ray is not installed. Install project dependencies (ray is required)."
            )
        self._pipeline_config = pipeline_config
        self._batches: dict[str, _RayBatchState] = {}

    def _ensure_initialized(self) -> None:
        if not ray.is_initialized():
            ray_cfg = self._pipeline_config.execution.ray
            ray.init(address=ray_cfg.address, ignore_reinit_error=True)

    async def submit(
        self,
        pipeline: IngestionPipeline,
        file_tasks: list[FileMetadata],
    ) -> str:
        _ = pipeline  # ExecutionBackend protocol; Ray rebuilds from config on workers.

        self._ensure_initialized()

        ray_cfg = self._pipeline_config.execution.ray
        num_cpus = ray_cfg.num_cpus_per_task
        num_gpus = ray_cfg.num_gpus_per_task
        max_retries = ray_cfg.max_retries

        config_dict = self._pipeline_config.model_dump(mode="json")
        remote_fn = _execute_pipeline_file_remote.options(
            num_cpus=num_cpus,
            num_gpus=num_gpus,
            max_retries=max_retries,
            runtime_env={"env_vars": _ray_worker_env_vars()},
        )

        batch_id = str(uuid.uuid4())
        refs = []
        for fm in file_tasks:
            ref = remote_fn.remote(config_dict, fm.file_path, asdict(fm))
            refs.append(ref)

        self._batches[batch_id] = _RayBatchState(
            total=len(file_tasks), refs=refs
        )
        return batch_id

    async def wait_for_batch(self, batch_id: str) -> dict:
        """Block until every task in the batch has finished (Ray workers)."""
        self._ensure_initialized()
        state = self._batches.get(batch_id)
        if state is None:
            raise KeyError(f"Unknown batch: {batch_id}")

        def _resolve_all_refs() -> None:
            for ref in state.refs:
                try:
                    ray.get(ref)
                except Exception:
                    pass

        await asyncio.to_thread(_resolve_all_refs)
        return await self.get_progress(batch_id)

    async def get_progress(self, batch_id: str) -> dict:
        state = self._batches.get(batch_id)
        if state is None:
            raise KeyError(f"Unknown batch: {batch_id}")

        # Drain any newly-finished refs into state.completed_results so that
        # results accumulate across repeated get_progress() / get_status() calls
        # instead of being lost after the first poll.
        still_pending = []
        for ref in state.refs:
            ready, _ = ray.wait([ref], timeout=0)
            if ready:
                try:
                    result = ray.get(ready[0])
                    state.completed_results.append(result)
                except Exception as exc:
                    state.completed_results.append(
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
        failed = sum(1 for r in state.completed_results if r.status == "failed")
        return {
            "total": state.total,
            "completed": len(state.completed_results) - failed,
            "failed": failed,
            "in_flight": [str(r) for r in state.refs],
            "results": list(state.completed_results),
        }

    async def cancel(self, batch_id: str) -> None:
        state = self._batches.get(batch_id)
        if state is None:
            return
        for ref in state.refs:
            ray.cancel(ref, force=True)
        state.refs.clear()


class _RayBatchState:
    __slots__ = ("total", "refs", "completed_results")

    def __init__(self, total: int, refs: list) -> None:
        self.total = total
        self.refs = refs  # still-pending ObjectRefs; drained as results arrive
        self.completed_results: list[PipelineResult] = []
