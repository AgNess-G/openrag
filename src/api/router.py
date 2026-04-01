"""Router endpoints that automatically route based on configuration settings."""

import json
import os
import tempfile
from typing import List, Optional

from fastapi import Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse

from config.settings import DISABLE_INGEST_WITH_LANGFLOW
from dependencies import (
    get_document_service,
    get_langflow_file_service,
    get_pipeline_config,
    get_session_manager,
    get_task_service,
    get_current_user,
)
from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)


async def upload_ingest_router(
    file: List[UploadFile] = File(...),
    session_id: Optional[str] = Form(None),
    settings_json: Optional[str] = Form(None, alias="settings"),
    tweaks_json: Optional[str] = Form(None, alias="tweaks"),
    delete_after_ingest: str = Form("true"),
    replace_duplicates: str = Form("true"),
    create_filter: str = Form("false"),
    document_service=Depends(get_document_service),
    langflow_file_service=Depends(get_langflow_file_service),
    session_manager=Depends(get_session_manager),
    task_service=Depends(get_task_service),
    pipeline_config=Depends(get_pipeline_config),
    user: User = Depends(get_current_user),
):
    """
    Router endpoint that automatically routes upload requests based on configuration.

    - If pipeline ingestion_mode == 'composable': routes through TaskService using
      ComposableFileProcessor so the task is trackable via /tasks/{task_id}.
    - If DISABLE_INGEST_WITH_LANGFLOW is True (and not composable): uses traditional
      OpenRAG upload.
    - Otherwise: uses Langflow upload-ingest via TaskService.
    """
    composable = (
        pipeline_config is not None
        and pipeline_config.ingestion_mode == "composable"
    )

    logger.debug(
        "Router upload_ingest endpoint called",
        mode="composable" if composable else "langflow",
        disable_langflow_ingest=DISABLE_INGEST_WITH_LANGFLOW,
    )

    # Traditional OpenRAG path only when Langflow is disabled AND we are not in
    # composable mode (composable always goes through TaskService for tracking).
    if DISABLE_INGEST_WITH_LANGFLOW and not composable:
        logger.debug("Routing to traditional OpenRAG upload")
        from api.upload import upload as traditional_upload_fn
        return await traditional_upload_fn(
            file=file[0] if file else None,
            document_service=document_service,
            session_manager=session_manager,
            user=user,
        )

    # Both Langflow and composable go through TaskService so every upload gets a
    # task_id that can be polled via GET /tasks/{task_id}.
    # create_langflow_upload_task() detects composable mode and switches to
    # ComposableFileProcessor automatically.
    logger.debug("Routing upload to TaskService", mode="composable" if composable else "langflow")
    return await _langflow_upload_ingest_task(
        upload_files=file,
        session_id=session_id,
        settings_json=settings_json,
        tweaks_json=tweaks_json,
        delete_after_ingest=delete_after_ingest.lower() == "true",
        replace_duplicates=replace_duplicates.lower() == "true",
        create_filter=create_filter.lower() == "true",
        langflow_file_service=langflow_file_service,
        session_manager=session_manager,
        task_service=task_service,
        user=user,
    )


async def _langflow_upload_ingest_task(
    upload_files: List[UploadFile],
    session_id,
    settings_json,
    tweaks_json,
    delete_after_ingest: bool,
    replace_duplicates: bool,
    create_filter: bool,
    langflow_file_service,
    session_manager,
    task_service,
    user: User,
):
    """Task-based langflow upload and ingest for single/multiple files"""
    try:
        if not upload_files:
            return JSONResponse({"error": "Missing files"}, status_code=400)

        settings = None
        tweaks = None

        if settings_json:
            try:
                settings = json.loads(settings_json)
            except json.JSONDecodeError as e:
                return JSONResponse({"error": f"Invalid settings JSON: {e}"}, status_code=400)

        if tweaks_json:
            try:
                tweaks = json.loads(tweaks_json)
            except json.JSONDecodeError as e:
                return JSONResponse({"error": f"Invalid tweaks JSON: {e}"}, status_code=400)

        user_id = user.user_id
        user_name = user.name
        user_email = user.email
        jwt_token = user.jwt_token

        temp_file_paths = []
        original_filenames = []

        try:
            temp_dir = tempfile.gettempdir()

            for upload_file in upload_files:
                content = await upload_file.read()
                original_filenames.append(upload_file.filename)
                safe_filename = upload_file.filename.replace(" ", "_").replace("/", "_")
                temp_path = os.path.join(temp_dir, safe_filename)
                with open(temp_path, "wb") as f:
                    f.write(content)
                temp_file_paths.append(temp_path)

            file_path_to_original_filename = dict(zip(temp_file_paths, original_filenames))

            task_id = await task_service.create_langflow_upload_task(
                user_id=user_id,
                file_paths=temp_file_paths,
                original_filenames=file_path_to_original_filename,
                langflow_file_service=langflow_file_service,
                session_manager=session_manager,
                jwt_token=jwt_token,
                owner_name=user_name,
                owner_email=user_email,
                session_id=session_id,
                tweaks=tweaks,
                settings=settings,
                delete_after_ingest=delete_after_ingest,
                replace_duplicates=replace_duplicates,
            )

            return JSONResponse(
                {
                    "task_id": task_id,
                    "message": f"Langflow upload task created for {len(upload_files)} file(s)",
                    "file_count": len(upload_files),
                    "create_filter": create_filter,
                    "filename": original_filenames[0] if len(original_filenames) == 1 else None,
                },
                status_code=202,
            )

        except Exception:
            from utils.file_utils import safe_unlink
            for temp_path in temp_file_paths:
                safe_unlink(temp_path)
            raise

    except Exception as e:
        logger.error("Task-based langflow upload_ingest failed", error=str(e))
        import traceback
        logger.error("Full traceback", traceback=traceback.format_exc())
        error_msg = str(e)
        if "AuthenticationException" in error_msg or "access denied" in error_msg.lower():
            return JSONResponse({"error": error_msg}, status_code=403)
        return JSONResponse({"error": error_msg}, status_code=500)
