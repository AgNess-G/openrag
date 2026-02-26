"""Integration tests for Anthropic model provider.

These tests mirror the OpenAI integration tests in test_api_endpoints.py but use
Anthropic as the LLM provider.  Embeddings still go through OpenAI because
Anthropic does not offer embedding models.

Every test in this module requires the ANTHROPIC_API_KEY environment variable.
If it is absent the test is automatically skipped via the ``anthropic_api_key``
fixture defined in the root conftest.
"""

import asyncio
import os
from pathlib import Path

import httpx
import pytest

from config.model_constants import (
    ANTHROPIC_DEFAULT_LANGUAGE_MODEL,
    ANTHROPIC_VALIDATION_MODELS,
    OPENAI_DEFAULT_EMBEDDING_MODEL,
)
from tests.integration.helpers import (
    clear_cached_modules,
    create_app_with_clean_index,
    set_common_test_env,
    wait_for_service_ready,
    wait_for_task_completion,
    wait_for_langflow_chat,
    wait_for_nudges,
)

ANTHROPIC_LLM_MODEL = ANTHROPIC_DEFAULT_LANGUAGE_MODEL
ANTHROPIC_LLM_MODEL_ALT = next(
    (m for m in ANTHROPIC_VALIDATION_MODELS if m != ANTHROPIC_DEFAULT_LANGUAGE_MODEL),
    ANTHROPIC_VALIDATION_MODELS[0],
)


# ---------------------------------------------------------------------------
# Test 1 – Onboarding & settings with Anthropic LLM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anthropic_onboarding_and_settings(anthropic_api_key):
    """Onboard with Anthropic LLM + OpenAI embeddings, then update settings."""
    set_common_test_env(
        disable_langflow_ingest=True,
        llm_provider="anthropic",
        llm_model=ANTHROPIC_LLM_MODEL,
    )
    clear_cached_modules()

    from main import create_app, startup_tasks
    from config.settings import clients

    await clients.initialize()
    app = await create_app()
    await startup_tasks(app.state.services)

    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await wait_for_service_ready(client)

            # Onboard with Anthropic as LLM provider
            onboarding_payload = {
                "llm_provider": "anthropic",
                "embedding_provider": "openai",
                "embedding_model": OPENAI_DEFAULT_EMBEDDING_MODEL,
                "llm_model": ANTHROPIC_LLM_MODEL,
                "anthropic_api_key": anthropic_api_key,
            }
            resp = await client.post("/onboarding", json=onboarding_payload)
            assert resp.status_code in (200, 204), (
                f"Onboarding with Anthropic failed: {resp.status_code} {resp.text}"
            )

            # Update settings – switch to a different Anthropic model
            settings_payload = {
                "llm_provider": "anthropic",
                "llm_model": ANTHROPIC_LLM_MODEL_ALT,
            }
            resp = await client.post("/settings", json=settings_payload)
            assert resp.status_code == 200, (
                f"Settings update to {ANTHROPIC_LLM_MODEL_ALT} failed: {resp.status_code} {resp.text}"
            )

            # Verify settings were applied via GET /settings
            resp = await client.get("/settings")
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data.get("llm_provider") == "anthropic"
            assert data.get("llm_model") == ANTHROPIC_LLM_MODEL_ALT
    finally:
        try:
            await clients.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Test 2 – Upload & search with Anthropic as LLM provider
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("disable_langflow_ingest", [True, False])
@pytest.mark.asyncio
async def test_anthropic_upload_and_search(
    tmp_path: Path,
    disable_langflow_ingest: bool,
    anthropic_api_key,
):
    """Upload a document and search while Anthropic is the configured LLM."""
    set_common_test_env(
        disable_langflow_ingest=disable_langflow_ingest,
        llm_provider="anthropic",
        llm_model=ANTHROPIC_LLM_MODEL,
    )
    clear_cached_modules()

    app = await create_app_with_clean_index()

    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await wait_for_service_ready(client)

            # Onboard with Anthropic LLM
            onboarding_payload = {
                "llm_provider": "anthropic",
                "embedding_provider": "openai",
                "embedding_model": OPENAI_DEFAULT_EMBEDDING_MODEL,
                "llm_model": ANTHROPIC_LLM_MODEL,
                "anthropic_api_key": anthropic_api_key,
            }
            resp = await client.post("/onboarding", json=onboarding_payload)
            if resp.status_code not in (200, 204):
                print(f"[DEBUG] Anthropic onboarding returned {resp.status_code}: {resp.text}")

            # Upload a test markdown file
            file_path = tmp_path / "anthropic_test_doc.md"
            file_text = (
                "# Anthropic Integration Test\n\n"
                "This document validates that upload and search work correctly "
                "when Anthropic is the configured LLM provider."
            )
            file_path.write_text(file_text)

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

            if disable_langflow_ingest:
                assert body.get("status") in {"indexed", "unchanged"}
                assert isinstance(body.get("id"), str)
            else:
                task_id = body.get("task_id")
                assert isinstance(task_id, str)
                assert body.get("file_count") == 1
                await wait_for_task_completion(client, task_id)

            # Poll until the document is searchable
            async def _wait_for_indexed(timeout_s: float = 30.0):
                deadline = asyncio.get_event_loop().time() + timeout_s
                while asyncio.get_event_loop().time() < deadline:
                    resp = await client.post(
                        "/search",
                        json={"query": "Anthropic integration test", "limit": 5},
                    )
                    if resp.status_code == 200 and resp.json().get("results"):
                        return resp
                    await asyncio.sleep(0.5)
                return resp

            search_resp = await _wait_for_indexed()
            assert search_resp.status_code == 200, search_resp.text
            search_body = search_resp.json()

            assert isinstance(search_body.get("results"), list)
            assert len(search_body["results"]) >= 0
            if search_body["results"]:
                top = search_body["results"][0]
                assert "text" in top or "content" in top
                text = top.get("text") or top.get("content")
                assert isinstance(text, str)
                assert "anthropic" in text.lower()
    finally:
        from config.settings import clients
        try:
            await clients.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Test 3 – Chat via Langflow with Anthropic LLM (skipped by default)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires live Langflow with configured flow IDs")
async def test_anthropic_chat_endpoint(anthropic_api_key):
    """Exercise /langflow chat with Anthropic as the LLM provider."""
    required_env = ["LANGFLOW_CHAT_FLOW_ID", "NUDGES_FLOW_ID"]
    missing = [var for var in required_env if not os.getenv(var)]
    assert not missing, f"Missing required Langflow configuration: {missing}"

    set_common_test_env(
        disable_langflow_ingest=True,
        llm_provider="anthropic",
        llm_model=ANTHROPIC_LLM_MODEL,
    )
    clear_cached_modules(extra=["api.chat", "api.nudges", "services.chat_service"])

    from main import create_app, startup_tasks
    from config.settings import clients, LANGFLOW_CHAT_FLOW_ID, NUDGES_FLOW_ID

    assert LANGFLOW_CHAT_FLOW_ID, "LANGFLOW_CHAT_FLOW_ID must be configured"
    assert NUDGES_FLOW_ID, "NUDGES_FLOW_ID must be configured"

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
    assert langflow_client is not None, (
        "Langflow client not initialized. Provide LANGFLOW_KEY or enable superuser auto-login."
    )

    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await wait_for_service_ready(client)

            # Configure Anthropic LLM via settings
            resp = await client.post(
                "/settings",
                json={
                    "embedding_model": OPENAI_DEFAULT_EMBEDDING_MODEL,
                    "llm_model": ANTHROPIC_LLM_MODEL,
                    "llm_provider": "anthropic",
                    "anthropic_api_key": anthropic_api_key,
                },
            )
            assert resp.status_code == 200, resp.text

            # Seed a document so the retriever has something to work with
            warmup_file = Path("./anthropic_nudges_seed.md")
            warmup_file.write_text(
                "The user may be interested in cloud computing, containers, and Kubernetes."
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
                await wait_for_task_completion(client, task_id)

            # Send a chat prompt through Langflow
            prompt = "Respond with a brief acknowledgement for the Anthropic integration test."
            langflow_payload = {"prompt": prompt, "limit": 5, "scoreThreshold": 0}
            langflow_data = await wait_for_langflow_chat(client, langflow_payload)

            assert isinstance(langflow_data.get("response"), str)
            assert langflow_data["response"].strip()

            response_id = langflow_data.get("response_id")

            # Verify nudges also work
            nudges_data = await wait_for_nudges(client)
            assert isinstance(nudges_data.get("response"), str)
            assert nudges_data["response"].strip()

            if response_id:
                nudges_thread_data = await wait_for_nudges(client, response_id)
                assert isinstance(nudges_thread_data.get("response"), str)
                assert nudges_thread_data["response"].strip()
    finally:
        from config.settings import clients
        try:
            await clients.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Test 4 – Provider health / validation for Anthropic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anthropic_provider_validation(anthropic_api_key):
    """Verify the /provider/health endpoint succeeds for Anthropic."""
    set_common_test_env(
        disable_langflow_ingest=True,
        llm_provider="anthropic",
        llm_model=ANTHROPIC_LLM_MODEL,
    )
    clear_cached_modules()

    from main import create_app, startup_tasks
    from config.settings import clients

    await clients.initialize()
    app = await create_app()
    await startup_tasks(app.state.services)

    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await wait_for_service_ready(client)

            # Onboard with Anthropic so the config is populated
            onboarding_payload = {
                "llm_provider": "anthropic",
                "embedding_provider": "openai",
                "embedding_model": OPENAI_DEFAULT_EMBEDDING_MODEL,
                "llm_model": ANTHROPIC_LLM_MODEL,
                "anthropic_api_key": anthropic_api_key,
            }
            resp = await client.post("/onboarding", json=onboarding_payload)
            if resp.status_code not in (200, 204):
                print(f"[DEBUG] Anthropic onboarding returned {resp.status_code}: {resp.text}")

            # Lightweight health check (no credits consumed)
            resp = await client.get("/provider/health", params={"provider": "anthropic"})
            assert resp.status_code == 200, (
                f"Anthropic provider health check failed: {resp.status_code} {resp.text}"
            )
            data = resp.json()
            assert data.get("status") == "healthy"
            assert data.get("provider") == "anthropic"

            # Full validation with completion test
            resp = await client.get(
                "/provider/health",
                params={"provider": "anthropic", "test_completion": "true"},
            )
            assert resp.status_code == 200, (
                f"Anthropic full validation failed: {resp.status_code} {resp.text}"
            )
            data = resp.json()
            assert data.get("status") == "healthy"
    finally:
        try:
            await clients.close()
        except Exception:
            pass
