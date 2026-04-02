from types import SimpleNamespace

import pytest

import config.settings as app_settings


def _make_config(backend: str = "opensearch"):
    return SimpleNamespace(knowledge=SimpleNamespace(backend=backend))


def test_normalize_knowledge_backend_defaults_and_alias():
    assert app_settings.normalize_knowledge_backend(None) == "opensearch"
    assert app_settings.normalize_knowledge_backend("") == "opensearch"
    assert app_settings.normalize_knowledge_backend("astradb") == "astra"
    assert app_settings.normalize_knowledge_backend("astra") == "astra"
    assert app_settings.normalize_knowledge_backend("opensearch") == "opensearch"


def test_normalize_knowledge_backend_rejects_invalid_value():
    with pytest.raises(ValueError, match="Unsupported knowledge backend"):
        app_settings.normalize_knowledge_backend("pinecone")


def test_get_knowledge_backend_prefers_env_override(monkeypatch):
    monkeypatch.setattr(
        app_settings,
        "get_openrag_config",
        lambda: _make_config("opensearch"),
        raising=True,
    )
    monkeypatch.setenv("VECTOR_BACKEND", "astradb")

    assert app_settings.get_knowledge_backend() == "astra"
    assert app_settings.is_astra_backend() is True


def test_validate_knowledge_backend_config_requires_astra_env(monkeypatch):
    monkeypatch.setattr(
        app_settings,
        "get_openrag_config",
        lambda: _make_config("astra"),
        raising=True,
    )
    monkeypatch.delenv("VECTOR_BACKEND", raising=False)
    monkeypatch.delenv("ASTRA_DB_APPLICATION_TOKEN", raising=False)
    monkeypatch.delenv("ASTRA_DB_API_ENDPOINT", raising=False)

    with pytest.raises(ValueError, match="ASTRA_DB_APPLICATION_TOKEN, ASTRA_DB_API_ENDPOINT"):
        app_settings.validate_knowledge_backend_config()


def test_validate_knowledge_backend_config_ignores_non_astra(monkeypatch):
    monkeypatch.setattr(
        app_settings,
        "get_openrag_config",
        lambda: _make_config("opensearch"),
        raising=True,
    )
    monkeypatch.delenv("VECTOR_BACKEND", raising=False)
    monkeypatch.delenv("ASTRA_DB_APPLICATION_TOKEN", raising=False)
    monkeypatch.delenv("ASTRA_DB_API_ENDPOINT", raising=False)

    app_settings.validate_knowledge_backend_config()


def test_active_flow_resolution_switches_with_backend(monkeypatch):
    monkeypatch.setattr(
        app_settings,
        "get_openrag_config",
        lambda: _make_config("opensearch"),
        raising=True,
    )
    monkeypatch.delenv("VECTOR_BACKEND", raising=False)

    assert app_settings.get_active_chat_flow_id() == (
        app_settings.LANGFLOW_CHAT_FLOW_ID or "1098eea1-6649-4e1d-aed1-b77249fb8dd0"
    )
    assert app_settings.get_active_flow_file_name("retrieval") == "openrag_agent.json"

    monkeypatch.setenv("VECTOR_BACKEND", "astra")

    assert app_settings.get_active_chat_flow_id() == app_settings.ASTRA_CHAT_FLOW_ID
    assert app_settings.get_active_ingest_flow_id() == app_settings.ASTRA_INGEST_FLOW_ID
    assert app_settings.get_active_url_ingest_flow_id() == app_settings.ASTRA_URL_INGEST_FLOW_ID
    assert app_settings.get_active_nudges_flow_id() == app_settings.ASTRA_NUDGES_FLOW_ID
    assert app_settings.get_active_flow_file_name("retrieval") == "openrag_agent_astra.json"
    assert app_settings.get_active_flow_file_name("ingest") == "ingestion_flow_astra.json"

