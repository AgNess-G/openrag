"""
Integration tests for the document lifecycle endpoints:
  GET  /documents/check-filename?filename=<name>
  POST /documents/delete-by-filename  {"filename": str}
  POST /upload_path                   {"path": str}

Tests run against an in-process FastAPI app with live OpenSearch.
No mocking needed — all assertions are based on confirmed response
shapes in src/api/documents.py and src/api/upload.py.
"""
import asyncio

import pytest

from tests.integration.core.helpers import boot_app, wait_for_task_completion


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _upload_md(client, filename: str, content: str):
    """Upload a markdown file via /router/upload_ingest and return the response."""
    files = {"file": (filename, content.encode(), "text/markdown")}
    return await client.post("/router/upload_ingest", files=files)


async def _check_exists(client, filename: str) -> bool:
    r = await client.get("/documents/check-filename", params={"filename": filename})
    assert r.status_code == 200, f"check-filename failed: {r.text}"
    return r.json()["exists"]


# ---------------------------------------------------------------------------
# Tests — check-filename endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_filename_not_exists(tmp_path):
    """Querying a filename that was never uploaded returns exists=False."""
    app, client = await boot_app()
    try:
        r = await client.get(
            "/documents/check-filename", params={"filename": "ghost_file_abc123.md"}
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["exists"] is False
        assert body["filename"] == "ghost_file_abc123.md"
    finally:
        await client.aclose()
        from config.settings import clients
        await clients.cleanup()


@pytest.mark.asyncio
async def test_check_filename_exists_after_upload(tmp_path):
    """A filename is discoverable via check-filename after a successful upload."""
    app, client = await boot_app()
    try:
        resp = await _upload_md(client, "existence_check.md", "# Existence check\n\nOpenRAG existence test.")
        assert resp.status_code in (201, 202), resp.text

        # Poll until indexed (max 30 s)
        deadline = asyncio.get_event_loop().time() + 30
        found = False
        while asyncio.get_event_loop().time() < deadline:
            if await _check_exists(client, "existence_check.md"):
                found = True
                break
            await asyncio.sleep(1)

        assert found, "File was not discoverable via check-filename within 30 s"
    finally:
        await client.aclose()
        from config.settings import clients
        await clients.cleanup()


# ---------------------------------------------------------------------------
# Tests — delete-by-filename endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_empty_filename(tmp_path):
    """Empty filename returns 400 with 'Filename is required' error."""
    app, client = await boot_app()
    try:
        r = await client.post("/documents/delete-by-filename", json={"filename": ""})
        assert r.status_code == 400, r.text
        body = r.json()
        assert body["success"] is False
        assert body["deleted_chunks"] == 0
        assert "required" in body["error"].lower()
    finally:
        await client.aclose()
        from config.settings import clients
        await clients.cleanup()


@pytest.mark.asyncio
async def test_delete_invalid_body(tmp_path):
    """Missing 'filename' key in request body returns 422 (FastAPI validation)."""
    app, client = await boot_app()
    try:
        r = await client.post("/documents/delete-by-filename", json={"wrong_key": "val"})
        assert r.status_code == 422, r.text
    finally:
        await client.aclose()
        from config.settings import clients
        await clients.cleanup()


@pytest.mark.asyncio
async def test_delete_not_found(tmp_path):
    """Deleting a filename that was never uploaded returns 404."""
    app, client = await boot_app()
    try:
        r = await client.post(
            "/documents/delete-by-filename", json={"filename": "ghost_doc_xyz.md"}
        )
        assert r.status_code == 404, r.text
        body = r.json()
        assert body["success"] is False
        assert body["deleted_chunks"] == 0
        assert body["error"] is not None
    finally:
        await client.aclose()
        from config.settings import clients
        await clients.cleanup()


@pytest.mark.asyncio
async def test_delete_then_check_gone(tmp_path):
    """Upload → confirm exists → delete → confirm gone (full document lifecycle)."""
    app, client = await boot_app()
    try:
        # 1. Upload
        resp = await _upload_md(
            client,
            "deletable_doc.md",
            "# Deletable document\n\nOpenRAG delete lifecycle test.",
        )
        assert resp.status_code in (201, 202), resp.text

        # 2. Wait until indexed and confirm exists
        deadline = asyncio.get_event_loop().time() + 30
        found = False
        while asyncio.get_event_loop().time() < deadline:
            if await _check_exists(client, "deletable_doc.md"):
                found = True
                break
            await asyncio.sleep(1)
        assert found, "File was not indexed within 30 s"

        # 3. Delete
        del_resp = await client.post(
            "/documents/delete-by-filename", json={"filename": "deletable_doc.md"}
        )
        assert del_resp.status_code == 200, del_resp.text
        del_body = del_resp.json()
        assert del_body["success"] is True
        assert del_body["deleted_chunks"] >= 1

        # 4. Confirm gone (OpenSearch may need a moment to reflect deletion)
        deadline2 = asyncio.get_event_loop().time() + 15
        gone = False
        while asyncio.get_event_loop().time() < deadline2:
            if not await _check_exists(client, "deletable_doc.md"):
                gone = True
                break
            await asyncio.sleep(1)
        assert gone, "File still shows as existing after deletion"
    finally:
        await client.aclose()
        from config.settings import clients
        await clients.cleanup()


# ---------------------------------------------------------------------------
# Tests — upload_path endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_path_invalid_path(tmp_path):
    """Providing a non-existent directory returns 400."""
    app, client = await boot_app()
    try:
        r = await client.post(
            "/upload_path", json={"path": "/nonexistent/path/xyz123"}
        )
        assert r.status_code == 400, r.text
        assert "error" in r.json()
    finally:
        await client.aclose()
        from config.settings import clients
        await clients.cleanup()


@pytest.mark.asyncio
async def test_upload_path_empty_directory(tmp_path):
    """An empty directory returns 400 with 'No files found'."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    app, client = await boot_app()
    try:
        r = await client.post("/upload_path", json={"path": str(empty_dir)})
        assert r.status_code == 400, r.text
        assert "No files found" in r.json()["error"]
    finally:
        await client.aclose()
        from config.settings import clients
        await clients.cleanup()


@pytest.mark.asyncio
async def test_upload_path_creates_task_and_completes(tmp_path):
    """Directory upload creates a task that completes successfully."""
    (tmp_path / "doc1.md").write_text("# Doc 1\n\nFirst document for upload_path test.")
    (tmp_path / "doc2.md").write_text("# Doc 2\n\nSecond document for upload_path test.")

    app, client = await boot_app()
    try:
        r = await client.post("/upload_path", json={"path": str(tmp_path)})
        assert r.status_code == 201, r.text
        body = r.json()
        assert "task_id" in body, body
        assert body["total_files"] == 2
        assert body["status"] == "accepted"

        # Poll until task completes
        task = await wait_for_task_completion(client, body["task_id"], timeout_s=120)
        assert task["status"] == "completed", f"Task failed: {task}"
    finally:
        await client.aclose()
        from config.settings import clients
        await clients.cleanup()
