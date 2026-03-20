import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from services.langflow_file_service import LangflowFileService
from services.langflow_mcp_service import LangflowMCPService
from utils.langflow_headers import build_mcp_global_vars_from_config


class _Resp:
    def __init__(self, status_code=200, payload=None, text="ok", content_type="application/json"):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.reason_phrase = "OK"
        self.headers = {"content-type": content_type}
        self.request = None

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}: {self.text}")


def _config(selected_provider: str = "openai"):
    return SimpleNamespace(
        knowledge=SimpleNamespace(
            embedding_model="text-embedding-3-small",
            embedding_provider=selected_provider,
        ),
        providers=SimpleNamespace(
            openai=SimpleNamespace(api_key="openai-key", configured=True),
            anthropic=SimpleNamespace(api_key="anthropic-key", configured=True),
            watsonx=SimpleNamespace(api_key="wx-key", project_id="wx-proj", endpoint="https://wx", configured=True),
            ollama=SimpleNamespace(endpoint="http://localhost:11434", configured=True),
        ),
    )


@pytest.mark.asyncio
async def test_url_ingestion_headers_only_include_selected_provider_credentials():
    """Selected embedding provider should be the only provider-specific credential sent."""
    service = LangflowFileService(flows_service=None)
    service.flow_id_url_ingest = "flow-1"

    async def _request(method, path, **kwargs):
        if method == "GET" and path == "/api/v1/flows/flow-1":
            return _Resp(status_code=200, payload={"id": "flow-1"})
        if method == "POST" and path == "/api/v1/run/flow-1":
            return _Resp(status_code=200, payload={"ok": True})
        raise AssertionError(f"unexpected request: {method} {path}")

    with (
        patch("services.langflow_file_service.clients.langflow_request", new=AsyncMock(side_effect=_request)) as req_mock,
        patch("config.settings.get_openrag_config", return_value=_config("openai")),
    ):
        await service.run_url_ingestion_flow("https://example.com", crawl_depth=1)

    post_call = [c for c in req_mock.call_args_list if c.args[:2] == ("POST", "/api/v1/run/flow-1")][0]
    headers = post_call.kwargs["headers"]

    assert headers["X-Langflow-Global-Var-SELECTED_EMBEDDING_MODEL"] == "text-embedding-3-small"
    assert "X-LANGFLOW-GLOBAL-VAR-OPENAI_API_KEY" in headers
    # Expected provider-agnostic rule: do not send non-selected providers.
    assert "X-LANGFLOW-GLOBAL-VAR-OLLAMA_BASE_URL" not in headers
    assert "X-LANGFLOW-GLOBAL-VAR-ANTHROPIC_API_KEY" not in headers
    assert "X-LANGFLOW-GLOBAL-VAR-WATSONX_APIKEY" not in headers


@pytest.mark.asyncio
async def test_url_ingest_flow_id_prefers_runtime_resolved_id_over_stale_config():
    """When flow resolver returns a newer ID, URL ingestion should run against it."""
    flows_service = SimpleNamespace(resolve_flow_id=AsyncMock(return_value="flow-new"))
    service = LangflowFileService(flows_service=flows_service)
    service.flow_id_url_ingest = "flow-old"

    async def _request(method, path, **kwargs):
        if method == "GET" and path == "/api/v1/flows/flow-new":
            return _Resp(status_code=200, payload={"id": "flow-new"})
        if method == "POST" and path == "/api/v1/run/flow-new":
            return _Resp(status_code=200, payload={"ok": True})
        # If stale flow is used, fail loudly.
        if "/flow-old" in path:
            raise AssertionError("stale flow id used")
        raise AssertionError(f"unexpected request: {method} {path}")

    with (
        patch("services.langflow_file_service.clients.langflow_request", new=AsyncMock(side_effect=_request)),
        patch("config.settings.get_openrag_config", return_value=_config("openai")),
        patch("utils.langflow_headers.add_provider_credentials_to_headers", new=AsyncMock(return_value=None)),
    ):
        await service.run_url_ingestion_flow("https://example.com", crawl_depth=1)

    flows_service.resolve_flow_id.assert_awaited_once_with("url_ingest", "flow-old")


@pytest.mark.asyncio
async def test_url_ingestion_reconciles_and_retries_once_on_known_stale_state_error():
    service = LangflowFileService(flows_service=None)
    service.flow_id_url_ingest = "flow-1"
    service._reconcile_url_ingestion_runtime_state = AsyncMock(return_value=None)

    calls = {"run": 0}

    async def _request(method, path, **kwargs):
        if method == "GET" and path == "/api/v1/flows/flow-1":
            return _Resp(status_code=200, payload={"id": "flow-1"})
        if method == "POST" and path == "/api/v1/run/flow-1":
            calls["run"] += 1
            if calls["run"] == 1:
                return _Resp(
                    status_code=500,
                    text='{"detail":"Failed to connect to Ollama"}',
                    payload={"detail": "Failed to connect to Ollama"},
                )
            return _Resp(status_code=200, payload={"ok": True})
        raise AssertionError(f"unexpected request: {method} {path}")

    with (
        patch("services.langflow_file_service.clients.langflow_request", new=AsyncMock(side_effect=_request)),
        patch("config.settings.get_openrag_config", return_value=_config("openai")),
    ):
        result = await service.run_url_ingestion_flow("https://example.com", crawl_depth=1)

    assert result == {"ok": True}
    service._reconcile_url_ingestion_runtime_state.assert_awaited_once_with("openai")
    assert calls["run"] == 2


@pytest.mark.asyncio
async def test_url_ingestion_does_not_retry_for_non_reconcilable_error():
    service = LangflowFileService(flows_service=None)
    service.flow_id_url_ingest = "flow-1"
    service._reconcile_url_ingestion_runtime_state = AsyncMock(return_value=None)

    calls = {"run": 0}

    async def _request(method, path, **kwargs):
        if method == "GET" and path == "/api/v1/flows/flow-1":
            return _Resp(status_code=200, payload={"id": "flow-1"})
        if method == "POST" and path == "/api/v1/run/flow-1":
            calls["run"] += 1
            return _Resp(
                status_code=500,
                text='{"detail":"OpenSearch timeout"}',
                payload={"detail": "OpenSearch timeout"},
            )
        raise AssertionError(f"unexpected request: {method} {path}")

    with (
        patch("services.langflow_file_service.clients.langflow_request", new=AsyncMock(side_effect=_request)),
        patch("config.settings.get_openrag_config", return_value=_config("openai")),
        pytest.raises(RuntimeError),
    ):
        await service.run_url_ingestion_flow("https://example.com", crawl_depth=1)

    service._reconcile_url_ingestion_runtime_state.assert_not_awaited()
    assert calls["run"] == 1


@pytest.mark.asyncio
async def test_url_ingestion_retry_failure_returns_provider_specific_message():
    service = LangflowFileService(flows_service=None)
    service.flow_id_url_ingest = "flow-1"
    service._reconcile_url_ingestion_runtime_state = AsyncMock(return_value=None)

    calls = {"run": 0}

    async def _request(method, path, **kwargs):
        if method == "GET" and path == "/api/v1/flows/flow-1":
            return _Resp(status_code=200, payload={"id": "flow-1"})
        if method == "POST" and path == "/api/v1/run/flow-1":
            calls["run"] += 1
            if calls["run"] == 1:
                return _Resp(
                    status_code=500,
                    text='{"detail":"Failed to connect to Ollama"}',
                    payload={"detail": "Failed to connect to Ollama"},
                )
            return _Resp(
                status_code=500,
                text='{"detail":"AuthenticationException(401, \'\')"}',
                payload={"detail": "AuthenticationException(401, '')"},
            )
        raise AssertionError(f"unexpected request: {method} {path}")

    with (
        patch("services.langflow_file_service.clients.langflow_request", new=AsyncMock(side_effect=_request)),
        patch("config.settings.get_openrag_config", return_value=_config("openai")),
        pytest.raises(ValueError, match="provider 'openai'"),
    ):
        await service.run_url_ingestion_flow("https://example.com", crawl_depth=1)

    assert calls["run"] == 2


@pytest.mark.asyncio
async def test_integration_style_selected_provider_mcp_and_self_heal_flow():
    """Integration-style (mocked HTTP): MCP provider pruning + URL self-heal retry."""
    cfg = _config("openai")

    # 1) Build selected-provider MCP vars and patch existing MCP args (with stale ollama header).
    mcp_vars = await build_mcp_global_vars_from_config(cfg, flows_service=None)
    mcp_service = LangflowMCPService()
    args = [
        "mcp-proxy",
        "--headers", "X-Langflow-Global-Var-OPENAI_API_KEY", "old-openai",
        "--headers", "X-Langflow-Global-Var-OLLAMA_BASE_URL", "http://localhost:11434",
        "--headers", "X-Langflow-Global-Var-SELECTED_EMBEDDING_MODEL", "old-model",
    ]
    updated_args = mcp_service._upsert_global_var_headers_in_args(args, mcp_vars)
    updated_joined = " ".join(updated_args)
    assert "X-Langflow-Global-Var-OPENAI_API_KEY openai-key" in updated_joined
    assert "X-Langflow-Global-Var-SELECTED_EMBEDDING_MODEL text-embedding-3-small" in updated_joined
    assert "X-Langflow-Global-Var-OLLAMA_BASE_URL" not in updated_joined

    # 2) URL ingestion stale-state first error -> one reconcile -> retry success.
    service = LangflowFileService(flows_service=None)
    service.flow_id_url_ingest = "flow-1"
    service._reconcile_url_ingestion_runtime_state = AsyncMock(return_value=None)

    calls = {"run": 0}

    async def _request(method, path, **kwargs):
        if method == "GET" and path == "/api/v1/flows/flow-1":
            return _Resp(status_code=200, payload={"id": "flow-1"})
        if method == "POST" and path == "/api/v1/run/flow-1":
            calls["run"] += 1
            # Stale-state signature from old runtime config.
            if calls["run"] == 1:
                return _Resp(
                    status_code=500,
                    text='{"detail":"Failed to connect to Ollama"}',
                    payload={"detail": "Failed to connect to Ollama"},
                )
            # Reconcile + retry succeeds.
            return _Resp(status_code=200, payload={"ok": True})
        raise AssertionError(f"unexpected request: {method} {path}")

    with (
        patch("services.langflow_file_service.clients.langflow_request", new=AsyncMock(side_effect=_request)) as req_mock,
        patch("config.settings.get_openrag_config", return_value=cfg),
    ):
        result = await service.run_url_ingestion_flow("https://example.com", crawl_depth=1)

    post_call = [c for c in req_mock.call_args_list if c.args[:2] == ("POST", "/api/v1/run/flow-1")][0]
    headers = post_call.kwargs["headers"]
    assert "X-LANGFLOW-GLOBAL-VAR-OPENAI_API_KEY" in headers
    assert "X-LANGFLOW-GLOBAL-VAR-OLLAMA_BASE_URL" not in headers
    assert result == {"ok": True}
    assert calls["run"] == 2
