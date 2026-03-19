"""Shared helpers for integration tests."""
import asyncio
import os
import sys

import httpx


def _clear_modules():
    """Clear cached modules so settings pick up env vars and router sees new flags."""
    for mod in [
        "api.router",
        "api.connector_router",
        "config.settings",
        "auth_middleware",
        "main",
        "api",
        "services",
        "services.search_service",
    ]:
        sys.modules.pop(mod, None)


async def boot_app(
    *,
    disable_startup_ingest: bool = True,
    disable_langflow_ingest: bool = True,
    clean_index: bool = True,
):
    """
    Boot a fresh in-process FastAPI app and return (app, client).

    The caller is responsible for closing the client and calling clients.cleanup()
    in a finally block.

    Usage:
        app, client = await boot_app()
        try:
            resp = await client.get("/settings")
        finally:
            await client.aclose()
            from config.settings import clients
            await clients.cleanup()
    """
    os.environ["DISABLE_INGEST_WITH_LANGFLOW"] = "true" if disable_langflow_ingest else "false"
    os.environ["DISABLE_STARTUP_INGEST"] = "true" if disable_startup_ingest else "false"
    os.environ["GOOGLE_OAUTH_CLIENT_ID"] = ""
    os.environ["GOOGLE_OAUTH_CLIENT_SECRET"] = ""

    _clear_modules()

    from main import create_app, startup_tasks
    from config.settings import clients, get_index_name

    await clients.initialize()

    if clean_index:
        try:
            await clients.opensearch.indices.delete(index=get_index_name())
            await asyncio.sleep(1)
        except Exception:
            pass

    app = await create_app()
    await startup_tasks(app.state.services)

    from main import _ensure_opensearch_index
    await _ensure_opensearch_index()

    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")

    return app, client


async def wait_for_task_completion(client: httpx.AsyncClient, task_id: str, timeout_s: float = 120.0) -> dict:
    """Poll GET /tasks/{task_id} until terminal state. Returns the final task dict."""
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        r = await client.get(f"/tasks/{task_id}")
        assert r.status_code == 200, f"Task status check failed: {r.text}"
        data = r.json()
        if data.get("status") in ("completed", "failed"):
            return data
        await asyncio.sleep(2)
    raise AssertionError(f"Task {task_id} did not complete within {timeout_s}s")


async def wait_for_indexed(
    client: httpx.AsyncClient, query: str, timeout_s: float = 30.0, min_results: int = 1
) -> dict:
    """Poll POST /search until at least min_results are returned."""
    deadline = asyncio.get_event_loop().time() + timeout_s
    last_resp = None
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.post("/search", json={"query": query, "limit": 5})
        if resp.status_code == 200:
            body = resp.json()
            if len(body.get("results", [])) >= min_results:
                return body
        last_resp = resp
        await asyncio.sleep(1)
    raise AssertionError(
        f"Query '{query}' returned no results within {timeout_s}s. "
        f"Last response: {last_resp.text if last_resp else 'none'}"
    )


async def is_docling_available() -> bool:
    """Returns True if docling-serve is reachable (needed for non-text format tests)."""
    try:
        from api.docling import DOCLING_SERVICE_URL
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{DOCLING_SERVICE_URL}/health", timeout=3.0)
            return r.status_code == 200
    except Exception:
        return False
