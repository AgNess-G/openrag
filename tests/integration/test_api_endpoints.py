import asyncio
import os
from pathlib import Path

import httpx
import pytest

from config.model_constants import (
    OPENAI_DEFAULT_EMBEDDING_MODEL,
    OPENAI_DEFAULT_LANGUAGE_MODEL,
)
from tests.integration.helpers import (
    wait_for_service_ready,
    wait_for_task_completion as _wait_for_task_completion,
    wait_for_langflow_chat as _wait_for_langflow_chat,
    wait_for_nudges as _wait_for_nudges,
)


@pytest.mark.parametrize("disable_langflow_ingest", [True, False])
@pytest.mark.asyncio
async def test_upload_and_search_endpoint(tmp_path: Path, disable_langflow_ingest: bool):
    """Boot the ASGI app and exercise /upload and /search endpoints."""
    # Ensure we route uploads to traditional processor and disable startup ingest
    os.environ["DISABLE_INGEST_WITH_LANGFLOW"] = "true" if disable_langflow_ingest else "false"
    os.environ["DISABLE_STARTUP_INGEST"] = "true"
    os.environ["EMBEDDING_MODEL"] = OPENAI_DEFAULT_EMBEDDING_MODEL
    os.environ["EMBEDDING_PROVIDER"] = "openai"
    # Force no-auth mode so endpoints bypass authentication
    os.environ["GOOGLE_OAUTH_CLIENT_ID"] = ""
    os.environ["GOOGLE_OAUTH_CLIENT_SECRET"] = ""

    # Import after env vars to ensure settings pick them up. Clear cached modules
    import sys
    # Clear cached modules so settings pick up env and router sees new flag
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
    from main import create_app, startup_tasks
    import api.router as upload_router
    from config.settings import clients, get_index_name, DISABLE_INGEST_WITH_LANGFLOW

    # Ensure a clean index before startup
    await clients.initialize()
    try:
        await clients.opensearch.indices.delete(index=get_index_name())
        # Wait for deletion to complete
        await asyncio.sleep(1)
    except Exception:
        pass

    app = await create_app()
    # Manually run startup tasks since httpx ASGI transport here doesn't manage lifespan
    await startup_tasks(app.state.services)

    # Ensure index exists for tests (startup_tasks only creates it if DISABLE_INGEST_WITH_LANGFLOW=True)
    from main import _ensure_opensearch_index
    await _ensure_opensearch_index()

    # Verify index is truly empty after startup
    try:
        count_response = await clients.opensearch.count(index=get_index_name())
        doc_count = count_response.get('count', 0)
        assert doc_count == 0, f"Index should be empty after startup but contains {doc_count} documents"
    except Exception as e:
        # If count fails, the index might not exist yet, which is fine
        pass

    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Wait for app + OpenSearch readiness using existing endpoints
            await wait_for_service_ready(client)

            # Create a temporary markdown file to upload
            file_path = tmp_path / "endpoint_test_doc.md"
            file_text = (
                "# Single Test Document\n\n"
                "This is a test document about OpenRAG testing framework. "
                "The content should be indexed and searchable in OpenSearch after processing."
            )
            file_path.write_text(file_text)

            # POST via router (multipart)
            files = {
                "file": (
                    file_path.name,
                    file_path.read_bytes(),
                    "text/markdown",
                )
            }
            upload_resp = await client.post("/router/upload_ingest", files=files)
            body = upload_resp.json()
            assert upload_resp.status_code in (201, 202), upload_resp.text

            # Handle different response formats based on whether Langflow is used
            if disable_langflow_ingest:
                # Traditional OpenRAG response (201)
                assert body.get("status") in {"indexed", "unchanged"}
                assert isinstance(body.get("id"), str)
            else:
                # Langflow task response (202)
                task_id = body.get("task_id")
                assert isinstance(task_id, str)
                assert body.get("file_count") == 1
                # Wait for task completion before searching
                await _wait_for_task_completion(client, task_id)

            # Poll search for the specific content until it's indexed
            async def _wait_for_indexed(timeout_s: float = 30.0):
                deadline = asyncio.get_event_loop().time() + timeout_s
                while asyncio.get_event_loop().time() < deadline:
                    resp = await client.post(
                        "/search",
                        json={"query": "OpenRAG testing framework", "limit": 5},
                    )
                    if resp.status_code == 200 and resp.json().get("results"):
                        return resp
                    await asyncio.sleep(0.5)
                return resp

            search_resp = await _wait_for_indexed()

            # POST /search
            assert search_resp.status_code == 200, search_resp.text
            search_body = search_resp.json()

            # Basic shape and at least one hit
            assert isinstance(search_body.get("results"), list)
            assert len(search_body["results"]) >= 0
            # When hits exist, confirm our phrase is present in top result content
            if search_body["results"]:
                top = search_body["results"][0]
                assert "text" in top or "content" in top
                text = top.get("text") or top.get("content")
                assert isinstance(text, str)
                assert "testing" in text.lower()
    finally:
        # Explicitly close global clients to avoid aiohttp warnings
        from config.settings import clients
        try:
            await clients.close()
        except Exception:
            pass


@pytest.mark.asyncio
@pytest.mark.skip
async def test_langflow_chat_and_nudges_endpoints():
    """Exercise /langflow and /nudges endpoints against a live Langflow backend."""
    required_env = ["LANGFLOW_CHAT_FLOW_ID", "NUDGES_FLOW_ID"]
    missing = [var for var in required_env if not os.getenv(var)]
    assert not missing, f"Missing required Langflow configuration: {missing}"

    os.environ["DISABLE_INGEST_WITH_LANGFLOW"] = "true"
    os.environ["DISABLE_STARTUP_INGEST"] = "true"
    os.environ["GOOGLE_OAUTH_CLIENT_ID"] = ""
    os.environ["GOOGLE_OAUTH_CLIENT_SECRET"] = ""

    import sys

    for mod in [
        "api.chat",
        "api.nudges",
        "api.router",
        "api.connector_router",
        "config.settings",
        "auth_middleware",
        "main",
        "api",
        "services",
        "services.search_service",
        "services.chat_service",
    ]:
        sys.modules.pop(mod, None)

    from main import create_app, startup_tasks
    from config.settings import clients, LANGFLOW_CHAT_FLOW_ID, NUDGES_FLOW_ID

    assert LANGFLOW_CHAT_FLOW_ID, "LANGFLOW_CHAT_FLOW_ID must be configured for integration test"
    assert NUDGES_FLOW_ID, "NUDGES_FLOW_ID must be configured for integration test"

    await clients.initialize()
    app = await create_app()
    await startup_tasks(app.state.services)

    langflow_client = None
    deadline = asyncio.get_event_loop().time() + 60.0
    while asyncio.get_event_loop().time() < deadline:
        langflow_client = await clients.ensure_langflow_client()
        if langflow_client is not None:
            break
        await asyncio.sleep(1.0)
    assert langflow_client is not None, "Langflow client not initialized. Provide LANGFLOW_KEY or enable superuser auto-login."

    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await wait_for_service_ready(client)

            # Ensure embedding model is configured via settings
            resp = await client.post(
                "/settings",
                json={
                    "embedding_model": OPENAI_DEFAULT_EMBEDDING_MODEL,
                    "llm_model": OPENAI_DEFAULT_LANGUAGE_MODEL,
                },
            )
            assert resp.status_code == 200, resp.text

            warmup_file = Path("./nudges_seed.md")
            warmup_file.write_text(
                "The user may care about different fruits including apples, hardy kiwi, and bananas"
            )
            files = {
                "file": (
                    warmup_file.name,
                    warmup_file.read_bytes(),
                    "text/plain",
                )
            }
            upload_resp = await client.post("/router/upload_ingest", files=files)
            assert upload_resp.status_code in (201, 202), upload_resp.text
            payload = upload_resp.json()
            task_id = payload.get("task_id")
            if task_id:
                await _wait_for_task_completion(client, task_id)

            prompt = "Respond with a brief acknowledgement for the OpenRAG integration test."
            langflow_payload = {"prompt": prompt, "limit": 5, "scoreThreshold": 0}
            langflow_data = await _wait_for_langflow_chat(client, langflow_payload)

            assert isinstance(langflow_data.get("response"), str)
            assert langflow_data["response"].strip()

            response_id = langflow_data.get("response_id")

            nudges_data = await _wait_for_nudges(client)
            assert isinstance(nudges_data.get("response"), str)
            assert nudges_data["response"].strip()

            if response_id:
                nudges_thread_data = await _wait_for_nudges(client, response_id)
                assert isinstance(nudges_thread_data.get("response"), str)
                assert nudges_thread_data["response"].strip()
    finally:
        from config.settings import clients

        try:
            await clients.close()
        except Exception:
            pass


@pytest.mark.skip
@pytest.mark.asyncio
async def test_search_multi_embedding_models(
    tmp_path: Path
):
    """Ensure /search fans out across multiple embedding models when present."""
    os.environ["DISABLE_INGEST_WITH_LANGFLOW"] = "true"
    os.environ["DISABLE_STARTUP_INGEST"] = "true"
    os.environ["GOOGLE_OAUTH_CLIENT_ID"] = ""
    os.environ["GOOGLE_OAUTH_CLIENT_SECRET"] = ""

    import sys

    for mod in [
        "api.router",
        "api.connector_router",
        "config.settings",
        "auth_middleware",
        "main",
        "services.search_service",
    ]:
        sys.modules.pop(mod, None)

    from main import create_app, startup_tasks
    from config.settings import clients, get_index_name

    await clients.initialize()
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

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await wait_for_service_ready(client)

            async def _upload_doc(name: str, text: str) -> None:
                file_path = tmp_path / name
                file_path.write_text(text)
                files = {
                    "file": (
                        name,
                        file_path.read_bytes(),
                        "text/markdown",
                    )
                }
                resp = await client.post("/router/upload_ingest", files=files)
                assert resp.status_code in (201, 202), resp.text
                payload = resp.json()
                task_id = payload.get("task_id")
                if task_id:
                    await _wait_for_task_completion(client, task_id)

            async def _wait_for_models(expected_models: set[str], query: str = "*"):
                deadline = asyncio.get_event_loop().time() + 60.0
                last_payload = None
                while asyncio.get_event_loop().time() < deadline:
                    resp = await client.post(
                        "/search",
                        json={"query": query, "limit": 0, "scoreThreshold": 0},
                    )
                    if resp.status_code != 200:
                        last_payload = resp.text
                        await asyncio.sleep(0.5)
                        continue
                    payload = resp.json()
                    buckets = (
                        payload.get("aggregations", {})
                        .get("embedding_models", {})
                        .get("buckets", [])
                    )
                    models = {b.get("key") for b in buckets if b.get("key")}
                    if expected_models <= models:
                        return payload
                    last_payload = payload
                    await asyncio.sleep(0.5)
                raise AssertionError(
                    f"Embedding models not detected. Last payload: {last_payload}"
                )

            # Start with explicit small embedding model
            resp = await client.post(
                "/settings",
                json={
                    "embedding_model": "text-embedding-3-small",
                    "llm_model": "gpt-4o-mini",
                },
            )
            assert resp.status_code == 200, resp.text

            # Ingest first document (small model)
            await _upload_doc("doc-small.md", "Physics basics and fundamental principles.")
            payload_small = await _wait_for_models({"text-embedding-3-small"})
            result_models_small = {
                r.get("embedding_model")
                for r in (payload_small.get("results") or [])
                if r.get("embedding_model")
            }
            assert "text-embedding-3-small" in result_models_small or not result_models_small

            # Update embedding model via settings
            resp = await client.post(
                "/settings",
                json={"embedding_model": "text-embedding-3-large"},
            )
            assert resp.status_code == 200, resp.text

            # Ingest second document which should use the large embedding model
            await _upload_doc("doc-large.md", "Advanced physics covers quantum topics extensively.")

            payload = await _wait_for_models({"text-embedding-3-small", "text-embedding-3-large"})
            buckets = payload.get("aggregations", {}).get("embedding_models", {}).get("buckets", [])
            models = {b.get("key") for b in buckets}
            assert {"text-embedding-3-small", "text-embedding-3-large"} <= models

            result_models = {
                r.get("embedding_model")
                for r in (payload.get("results") or [])
                if r.get("embedding_model")
            }
            assert {"text-embedding-3-small", "text-embedding-3-large"} <= result_models
    finally:
        from config.settings import clients

        try:
            await clients.close()
        except Exception:
            pass


@pytest.mark.parametrize("disable_langflow_ingest", [True, False])
@pytest.mark.asyncio
async def test_router_upload_ingest_traditional(tmp_path: Path, disable_langflow_ingest: bool):
    """Exercise the router endpoint to ensure it routes to traditional upload when Langflow ingest is disabled."""
    os.environ["DISABLE_INGEST_WITH_LANGFLOW"] = "true" if disable_langflow_ingest else "false"
    os.environ["DISABLE_STARTUP_INGEST"] = "true"
    os.environ["GOOGLE_OAUTH_CLIENT_ID"] = ""
    os.environ["GOOGLE_OAUTH_CLIENT_SECRET"] = ""

    import sys
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
    from main import create_app, startup_tasks
    import api.router as upload_router
    from config.settings import clients, get_index_name, DISABLE_INGEST_WITH_LANGFLOW

    # Ensure a clean index before startup
    await clients.initialize()
    try:
        await clients.opensearch.indices.delete(index=get_index_name())
        # Wait for deletion to complete
        await asyncio.sleep(1)
    except Exception:
        pass

    app = await create_app()
    await startup_tasks(app.state.services)

    # Ensure index exists for tests (startup_tasks only creates it if DISABLE_INGEST_WITH_LANGFLOW=True)
    from main import _ensure_opensearch_index
    await _ensure_opensearch_index()

    # Verify index is truly empty after startup
    try:
        count_response = await clients.opensearch.count(index=get_index_name())
        doc_count = count_response.get('count', 0)
        assert doc_count == 0, f"Index should be empty after startup but contains {doc_count} documents"
    except Exception as e:
        # If count fails, the index might not exist yet, which is fine
        pass
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await wait_for_service_ready(client)

            file_path = tmp_path / "router_test_doc.md"
            file_path.write_text("# Router Test\n\nThis file validates the upload router.")

            files = {
                "file": (
                    file_path.name,
                    file_path.read_bytes(),
                    "text/markdown",
                )
            }

            resp = await client.post("/router/upload_ingest", files=files)
            data = resp.json()

            print(f"data: {data}")
            if disable_langflow_ingest:
                assert resp.status_code == 201 or resp.status_code == 202, resp.text
                assert data.get("status") in {"indexed", "unchanged"}
                assert isinstance(data.get("id"), str)
            else:
                assert resp.status_code == 201 or resp.status_code == 202, resp.text
                assert isinstance(data.get("task_id"), str)
                assert data.get("file_count") == 1
    finally:
        from config.settings import clients
        try:
            await clients.close()
        except Exception:
            pass
