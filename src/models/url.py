import asyncio
import time
from typing import Any, Dict, Optional

from utils.logging_config import get_logger
from .processors import TaskProcessor
from .tasks import UploadTask, FileTask, TaskStatus

logger = get_logger(__name__)


class LangflowUrlProcessor(TaskProcessor):
    """Processor for Langflow URL ingestion flow as a tracked task."""

    def __init__(
        self,
        langflow_file_service,
        session_manager,
        docs_url: str,
        crawl_depth: int,
        owner_user_id: str = None,
        jwt_token: str = None,
        owner_name: str = None,
        owner_email: str = None,
        connector_type: str = "openrag_docs",
        prevent_outside: bool = True,
        tweaks: Optional[Dict[str, Any]] = None,
    ):
        super().__init__()
        self.langflow_file_service = langflow_file_service
        self.session_manager = session_manager
        self.docs_url = docs_url
        self.crawl_depth = crawl_depth
        self.owner_user_id = owner_user_id
        self.jwt_token = jwt_token
        self.owner_name = owner_name
        self.owner_email = owner_email
        self.connector_type = connector_type
        self.prevent_outside = prevent_outside
        self.tweaks = tweaks

    async def _count_system_default_docs(self, opensearch_client) -> int:
        """Count indexed OpenRAG docs for the current owner/context."""
        from config.settings import get_index_name

        must_filters = [
            {
                "bool": {
                    "should": [
                        {"term": {"connector_type.keyword": self.connector_type}},
                        {"term": {"connector_type": self.connector_type}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        ]
        if self.owner_email:
            must_filters.append(
                {
                    "bool": {
                        "should": [
                            {"term": {"owner_email.keyword": self.owner_email}},
                            {"match_phrase": {"owner_email": self.owner_email}},
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )
        if self.owner_user_id:
            must_filters.append(
                {
                    "bool": {
                        "should": [
                            {"term": {"owner.keyword": self.owner_user_id}},
                            {"match_phrase": {"owner": self.owner_user_id}},
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )

        count_query = {"query": {"bool": {"must": must_filters}}}
        response = await opensearch_client.count(
            index=get_index_name(),
            body=count_query,
        )
        return int(response.get("count", 0))

    async def process_item(
        self, upload_task: UploadTask, item: str, file_task: FileTask
    ) -> None:
        """Process one URL ingestion item through Langflow."""
        file_task.status = TaskStatus.RUNNING
        file_task.updated_at = time.time()

        try:
            effective_jwt = self.jwt_token
            if self.session_manager and not effective_jwt:
                self.session_manager.get_user_opensearch_client(
                    self.owner_user_id, self.jwt_token
                )
                if hasattr(self.session_manager, "_anonymous_jwt"):
                    effective_jwt = self.session_manager._anonymous_jwt

            opensearch_client = self.session_manager.get_user_opensearch_client(
                self.owner_user_id, effective_jwt
            )
            docs_before = await self._count_system_default_docs(opensearch_client)
            logger.info(
                "URL ingestion before",
                docs_before=docs_before,
            )

            result = await self.langflow_file_service.run_url_ingestion_flow(
                docs_url=self.docs_url,
                crawl_depth=self.crawl_depth,
                jwt_token=effective_jwt,
                owner=self.owner_user_id,
                owner_name=self.owner_name,
                owner_email=self.owner_email,
                connector_type=self.connector_type,
                prevent_outside=self.prevent_outside,
                tweaks=self.tweaks,
            )
            # docs_after = await self._count_system_default_docs(opensearch_client)
            # logger.info(
            #     "URL ingestion after",
            #     docs_after=docs_after,
            # )
            # # OpenSearch visibility can lag indexing by a refresh interval.
            # # Retry a few times before declaring ingestion failed.
            # for _ in range(5):
            #     if docs_after > 0:
            #         break
            #     await asyncio.sleep(1)
            #     docs_after = await self._count_system_default_docs(opensearch_client)
            # if docs_after <= 0:
            #     raise ValueError(
            #         "URL ingestion completed but no OpenRAG docs were indexed"
            #     )
            # logger.info(
            #     "URL ingestion indexed OpenRAG docs",
            #     docs_before=docs_before,
            #     docs_after=docs_after,
            # )

            file_task.status = TaskStatus.COMPLETED
            file_task.result = result
            file_task.updated_at = time.time()
            upload_task.successful_files += 1

        except Exception as e:
            file_task.status = TaskStatus.FAILED
            file_task.error = str(e)
            file_task.updated_at = time.time()
            upload_task.failed_files += 1
            raise


class ComposableUrlProcessor(TaskProcessor):
    """Processes a URL by crawling it to a temp file and feeding the composable pipeline."""

    def __init__(
        self,
        docs_url: str,
        crawl_depth: int,
        owner_user_id: str = None,
        jwt_token: str = None,
        owner_name: str = None,
        owner_email: str = None,
        connector_type: str = "openrag_docs",
    ):
        super().__init__()
        self.docs_url = docs_url
        self.crawl_depth = crawl_depth
        self.owner_user_id = owner_user_id
        self.jwt_token = jwt_token
        self.owner_name = owner_name
        self.owner_email = owner_email
        self.connector_type = connector_type

    async def process_item(
        self, upload_task: UploadTask, item: str, file_task: FileTask
    ) -> None:
        import hashlib
        import mimetypes
        import time as _time

        from main import _get_pipeline_service, _materialize_default_docs_url_as_text_file
        from models.tasks import TaskStatus as _TaskStatus
        from pipeline.ingestion.types import FileMetadata

        file_task.status = _TaskStatus.RUNNING
        file_task.updated_at = _time.time()

        try:
            pipeline_service = _get_pipeline_service()
            if pipeline_service is None:
                raise RuntimeError("PipelineService not available in composable mode")

            temp_path = await _materialize_default_docs_url_as_text_file(
                docs_url=self.docs_url,
                crawl_depth=self.crawl_depth,
            )
            try:
                with open(temp_path, "rb") as fh:
                    content = fh.read()
                file_hash = hashlib.sha256(content).hexdigest()
                mime, _ = mimetypes.guess_type(temp_path)

                fm = FileMetadata(
                    file_path=temp_path,
                    filename=f"url-{self.connector_type}.txt",
                    file_hash=file_hash,
                    file_size=len(content),
                    mimetype=mime or "text/plain",
                    owner_user_id=self.owner_user_id,
                    jwt_token=self.jwt_token,
                    connector_type=self.connector_type,
                    owner_name=self.owner_name,
                    owner_email=self.owner_email,
                    source_url=self.docs_url,
                )

                batch_id = await pipeline_service.run_files([fm])
                # Wait for the pipeline to finish before deleting the temp file
                # and before marking the task complete. The local backend submits
                # work as asyncio tasks (fire-and-forget), so without this wait
                # the temp file would be deleted before the parser reads it and
                # the task would be marked done while indexing is still running.
                progress = await pipeline_service.wait_for_batch(batch_id)

                results = progress.get("results", [])
                first = results[0] if results else None
                if first is not None and first.status == "failed":
                    raise RuntimeError(first.error or "Pipeline processing failed")

                file_task.status = _TaskStatus.COMPLETED
                result_data: dict = {"status": "indexed", "batch_id": batch_id}
                if first is not None:
                    result_data["chunks_indexed"] = first.chunks_indexed
                    result_data["chunks_total"] = first.chunks_total
                    result_data["pipeline_status"] = first.status
                    result_data["duration_seconds"] = round(first.duration_seconds, 2)
                file_task.result = result_data
                file_task.updated_at = _time.time()
                upload_task.successful_files += 1
            finally:
                try:
                    import os as _os
                    _os.unlink(temp_path)
                except FileNotFoundError:
                    pass

        except Exception as exc:
            file_task.status = _TaskStatus.FAILED
            file_task.error = str(exc)
            file_task.updated_at = _time.time()
            upload_task.failed_files += 1
            raise
