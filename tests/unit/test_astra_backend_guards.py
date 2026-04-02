from unittest.mock import AsyncMock, Mock

import pytest

import api.documents as documents_api
import config.settings as app_settings
from models.processors import LangflowFileProcessor
from models.tasks import FileTask, TaskStatus, UploadTask
from session_manager import User


@pytest.mark.asyncio
async def test_check_filename_exists_is_non_blocking_for_astra(monkeypatch):
    monkeypatch.setattr(app_settings, "is_astra_backend", lambda: True, raising=True)

    response = await documents_api.check_filename_exists(
        filename="example.pdf",
        session_manager=Mock(),
        user=User(user_id="u1", email="u1@example.com", name="User One"),
    )

    assert response.status_code == 200
    assert response.body == b'{"exists":false,"filename":"example.pdf"}'


@pytest.mark.asyncio
async def test_langflow_file_processor_skips_duplicate_checks_for_astra(monkeypatch, tmp_path):
    file_path = tmp_path / "report.txt"
    file_path.write_text("hello", encoding="utf-8")

    session_manager = Mock()
    langflow_file_service = Mock()
    langflow_file_service.upload_and_ingest_file = AsyncMock(return_value={"ok": True})

    processor = LangflowFileProcessor(
        langflow_file_service=langflow_file_service,
        session_manager=session_manager,
        owner_user_id="u1",
        jwt_token="jwt-token",
        replace_duplicates=True,
    )
    processor.check_filename_exists = AsyncMock(return_value=True)
    processor.delete_document_by_filename = AsyncMock()

    monkeypatch.setattr(app_settings, "is_astra_backend", lambda: True, raising=True)

    upload_task = UploadTask(
        task_id="task-1",
        total_files=1,
        file_tasks={str(file_path): FileTask(file_path=str(file_path), filename="report.txt")},
    )
    file_task = upload_task.file_tasks[str(file_path)]

    await processor.process_item(upload_task, str(file_path), file_task)

    processor.check_filename_exists.assert_not_awaited()
    processor.delete_document_by_filename.assert_not_awaited()
    assert file_task.status == TaskStatus.COMPLETED
    assert upload_task.successful_files == 1
    langflow_file_service.upload_and_ingest_file.assert_awaited_once()
