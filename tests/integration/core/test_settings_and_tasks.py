"""
Integration tests for settings and task API contracts.

Settings endpoints:
  GET  /settings
  POST /settings  (requires config.edited=True, set by the onboard_system session fixture)

Task endpoints:
  GET  /tasks
  GET  /tasks/{task_id}
  POST /tasks/{task_id}/cancel

All tests boot a fresh in-process app per test. Settings POST tests rely on
config/config.yaml being pre-initialised by the session-scoped onboard_system
fixture in tests/conftest.py — do NOT delete that file inside these tests.
"""
import asyncio
import os

import pytest

from tests.integration.core.helpers import boot_app, wait_for_task_completion


# ---------------------------------------------------------------------------
# Settings — GET /settings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_settings_shape(tmp_path):
    """GET /settings returns a dict with the expected top-level keys and sub-keys."""
    app, client = await boot_app(clean_index=False)
    try:
        r = await client.get("/settings")
        assert r.status_code == 200, r.text
        body = r.json()

        # Top-level keys
        for key in ("edited", "providers", "knowledge", "agent"):
            assert key in body, f"Missing top-level key: {key}"

        assert isinstance(body["edited"], bool)
        assert isinstance(body["providers"], dict)

        # knowledge sub-keys
        for key in ("embedding_model", "chunk_size", "chunk_overlap"):
            assert key in body["knowledge"], f"Missing knowledge.{key}"

        # agent sub-keys
        for key in ("llm_model", "llm_provider", "system_prompt"):
            assert key in body["agent"], f"Missing agent.{key}"
    finally:
        await client.aclose()
        from config.settings import clients
        await clients.cleanup()


@pytest.mark.asyncio
async def test_post_settings_updates_system_prompt(tmp_path):
    """POST /settings can update the system_prompt and GET /settings reflects the change."""
    app, client = await boot_app(clean_index=False)
    original_prompt = None
    try:
        # Capture current
        r = await client.get("/settings")
        assert r.status_code == 200
        original_prompt = r.json()["agent"].get("system_prompt", "")

        # Update
        new_prompt = "Integration test system prompt XYZ"
        r2 = await client.post("/settings", json={"system_prompt": new_prompt})
        assert r2.status_code == 200, r2.text

        # Verify
        r3 = await client.get("/settings")
        assert r3.status_code == 200
        assert r3.json()["agent"]["system_prompt"] == new_prompt
    finally:
        # Restore original
        if original_prompt is not None:
            try:
                await client.post("/settings", json={"system_prompt": original_prompt})
            except Exception:
                pass
        await client.aclose()
        from config.settings import clients
        await clients.cleanup()


@pytest.mark.asyncio
async def test_post_settings_updates_chunk_size(tmp_path):
    """POST /settings can update chunk_size and GET /settings reflects the change."""
    app, client = await boot_app(clean_index=False)
    original_chunk_size = None
    try:
        r = await client.get("/settings")
        assert r.status_code == 200
        original_chunk_size = r.json()["knowledge"].get("chunk_size")

        r2 = await client.post("/settings", json={"chunk_size": 512})
        assert r2.status_code == 200, r2.text

        r3 = await client.get("/settings")
        assert r3.status_code == 200
        assert r3.json()["knowledge"]["chunk_size"] == 512
    finally:
        if original_chunk_size is not None:
            try:
                await client.post("/settings", json={"chunk_size": original_chunk_size})
            except Exception:
                pass
        await client.aclose()
        from config.settings import clients
        await clients.cleanup()


# ---------------------------------------------------------------------------
# Settings — POST /settings validation (422s)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_settings_rejects_invalid_llm_provider(tmp_path):
    """An unrecognised llm_provider value returns 422."""
    app, client = await boot_app(clean_index=False)
    try:
        r = await client.post("/settings", json={"llm_provider": "not_a_real_provider"})
        assert r.status_code == 422, r.text
    finally:
        await client.aclose()
        from config.settings import clients
        await clients.cleanup()


@pytest.mark.asyncio
async def test_post_settings_rejects_zero_chunk_size(tmp_path):
    """chunk_size=0 violates gt=0 constraint and returns 422."""
    app, client = await boot_app(clean_index=False)
    try:
        r = await client.post("/settings", json={"chunk_size": 0})
        assert r.status_code == 422, r.text
    finally:
        await client.aclose()
        from config.settings import clients
        await clients.cleanup()


@pytest.mark.asyncio
async def test_post_settings_rejects_negative_chunk_overlap(tmp_path):
    """chunk_overlap=-1 violates ge=0 constraint and returns 422."""
    app, client = await boot_app(clean_index=False)
    try:
        r = await client.post("/settings", json={"chunk_overlap": -1})
        assert r.status_code == 422, r.text
    finally:
        await client.aclose()
        from config.settings import clients
        await clients.cleanup()


# ---------------------------------------------------------------------------
# Tasks — GET /tasks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_tasks_returns_list(tmp_path):
    """GET /tasks returns 200 with a 'tasks' list (may be empty)."""
    app, client = await boot_app(clean_index=False)
    try:
        r = await client.get("/tasks")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "tasks" in body
        assert isinstance(body["tasks"], list)
    finally:
        await client.aclose()
        from config.settings import clients
        await clients.cleanup()


# ---------------------------------------------------------------------------
# Tasks — GET /tasks/{task_id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_task_not_found(tmp_path):
    """GET /tasks/<nonexistent-id> returns 404 with 'Task not found'."""
    app, client = await boot_app(clean_index=False)
    try:
        r = await client.get("/tasks/nonexistent-task-id-00000")
        assert r.status_code == 404, r.text
        assert r.json()["error"] == "Task not found"
    finally:
        await client.aclose()
        from config.settings import clients
        await clients.cleanup()


# ---------------------------------------------------------------------------
# Tasks — POST /tasks/{task_id}/cancel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_task_not_found(tmp_path):
    """POST /tasks/<nonexistent-id>/cancel returns 400 with a 'not found' message."""
    app, client = await boot_app(clean_index=False)
    try:
        r = await client.post("/tasks/nonexistent-task-id-00000/cancel")
        assert r.status_code == 400, r.text
        assert "not found" in r.json()["error"].lower()
    finally:
        await client.aclose()
        from config.settings import clients
        await clients.cleanup()


# ---------------------------------------------------------------------------
# Tasks — full lifecycle via upload_path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_task_lifecycle_via_upload_path(tmp_path):
    """
    upload_path creates a task → task appears in GET /tasks → task completes.

    Exercises the full task lifecycle: creation, list, status polling, completion.
    """
    (tmp_path / "task_test1.md").write_text("# Task test 1\n\nFirst task lifecycle file.")
    (tmp_path / "task_test2.md").write_text("# Task test 2\n\nSecond task lifecycle file.")

    app, client = await boot_app()
    try:
        # Create a task via upload_path
        r = await client.post("/upload_path", json={"path": str(tmp_path)})
        assert r.status_code == 201, r.text
        task_id = r.json()["task_id"]
        assert task_id

        # Task should appear in GET /tasks
        r2 = await client.get("/tasks")
        assert r2.status_code == 200
        task_ids_in_list = [t["task_id"] for t in r2.json()["tasks"]]
        assert task_id in task_ids_in_list, f"task_id {task_id} not in /tasks response"

        # GET /tasks/{task_id} returns valid status
        r3 = await client.get(f"/tasks/{task_id}")
        assert r3.status_code == 200, r3.text
        body3 = r3.json()
        assert "status" in body3

        # Poll until completion
        final = await wait_for_task_completion(client, task_id, timeout_s=120)
        assert final["status"] == "completed", f"Task did not complete: {final}"
    finally:
        await client.aclose()
        from config.settings import clients
        await clients.cleanup()
