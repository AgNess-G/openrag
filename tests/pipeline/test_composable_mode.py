"""Tests for composable-mode Langflow-free functionality."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pipeline.config import DoclingOptions, EmbedderConfig, PipelineConfig
from pipeline.types import EmbeddedChunk, FileMetadata


# ---------------------------------------------------------------------------
# Phase 1: DoclingParser URL precedence
# ---------------------------------------------------------------------------


class TestDoclingParserUrl:
    """DoclingParser should prefer DOCLING_SERVE_URL over DOCLING_SERVICE_URL."""

    def test_uses_serve_url_env(self, monkeypatch):
        monkeypatch.setenv("DOCLING_SERVE_URL", "http://serve:5001")
        monkeypatch.delenv("DOCLING_SERVICE_URL", raising=False)

        from pipeline.parsers.docling import DoclingParser
        parser = DoclingParser()
        assert parser._service_url == "http://serve:5001"

    def test_falls_back_to_service_url(self, monkeypatch):
        monkeypatch.delenv("DOCLING_SERVE_URL", raising=False)
        monkeypatch.setenv("DOCLING_SERVICE_URL", "http://legacy:5001")

        from pipeline.parsers.docling import DoclingParser
        parser = DoclingParser()
        assert parser._service_url == "http://legacy:5001"

    def test_explicit_service_url_overrides_env(self, monkeypatch):
        monkeypatch.setenv("DOCLING_SERVE_URL", "http://serve:5001")

        from pipeline.parsers.docling import DoclingParser
        parser = DoclingParser(service_url="http://explicit:9999")
        assert parser._service_url == "http://explicit:9999"

    def test_default_url(self, monkeypatch):
        monkeypatch.delenv("DOCLING_SERVE_URL", raising=False)
        monkeypatch.delenv("DOCLING_SERVICE_URL", raising=False)

        from pipeline.parsers.docling import DoclingParser
        parser = DoclingParser()
        assert parser._service_url == "http://localhost:5001"


class TestDoclingOptionsConfig:
    """DoclingOptions should include serve_url and it should override from env."""

    def test_serve_url_field_exists(self):
        opts = DoclingOptions()
        assert opts.serve_url == ""

    def test_serve_url_env_override(self, monkeypatch):
        monkeypatch.setenv("DOCLING_SERVE_URL", "http://env-url:5001")

        from pipeline.config import PipelineConfigManager
        mgr = PipelineConfigManager()
        cfg = mgr.load(path=None)  # defaults
        assert cfg.parser.docling.serve_url == "http://env-url:5001"


# ---------------------------------------------------------------------------
# Phase 1b: FileMetadata extended fields
# ---------------------------------------------------------------------------


class TestFileMetadataExtended:
    def test_new_fields_have_defaults(self):
        fm = FileMetadata(
            file_path="/tmp/x",
            filename="x.txt",
            file_hash="aaa",
            file_size=10,
            mimetype="text/plain",
        )
        assert fm.owner_name is None
        assert fm.owner_email is None
        assert fm.source_url is None
        assert fm.document_id is None
        assert fm.is_sample_data is False

    def test_new_fields_set(self):
        fm = FileMetadata(
            file_path="/tmp/x",
            filename="x.txt",
            file_hash="aaa",
            file_size=10,
            mimetype="text/plain",
            owner_name="Alice",
            owner_email="alice@example.com",
            source_url="https://example.com/doc",
            document_id="doc-123",
            is_sample_data=True,
        )
        assert fm.owner_name == "Alice"
        assert fm.owner_email == "alice@example.com"
        assert fm.source_url == "https://example.com/doc"
        assert fm.document_id == "doc-123"
        assert fm.is_sample_data is True


# ---------------------------------------------------------------------------
# Phase 1b: Indexer writes extended fields
# ---------------------------------------------------------------------------


class TestIndexerExtendedFields:

    @pytest.fixture
    def metadata_with_extras(self, sample_text_file):
        return FileMetadata(
            file_path=sample_text_file,
            filename="sample.txt",
            file_hash="abc123",
            file_size=300,
            mimetype="text/plain",
            owner_name="Bob",
            owner_email="bob@example.com",
            source_url="https://example.com",
            document_id="ext-doc-1",
            is_sample_data=True,
        )

    @patch("utils.embedding_fields.ensure_embedding_field_exists", new_callable=AsyncMock)
    @patch("utils.embedding_fields.get_embedding_field_name", return_value="chunk_embedding_test")
    @patch("config.settings.get_index_name", return_value="test-index")
    def test_build_actions_includes_new_fields(
        self, mock_idx, mock_field, mock_ensure, metadata_with_extras, sample_embedded_chunks
    ):
        from pipeline.indexers.opensearch_bulk import OpenSearchBulkIndexer
        indexer = OpenSearchBulkIndexer(opensearch_client=AsyncMock())
        actions = indexer._build_actions(
            sample_embedded_chunks, metadata_with_extras, "test-index", "chunk_embedding_test"
        )
        doc_body = actions[1]
        assert doc_body["owner_name"] == "Bob"
        assert doc_body["owner_email"] == "bob@example.com"
        assert doc_body["source_url"] == "https://example.com"
        assert doc_body["is_sample_data"] is True
        assert doc_body["document_id"] == "ext-doc-1"

    @patch("utils.embedding_fields.ensure_embedding_field_exists", new_callable=AsyncMock)
    @patch("utils.embedding_fields.get_embedding_field_name", return_value="chunk_embedding_test")
    @patch("config.settings.get_index_name", return_value="test-index")
    def test_build_actions_uses_document_id_for_opensearch_id(
        self, mock_idx, mock_field, mock_ensure, metadata_with_extras, sample_embedded_chunks
    ):
        from pipeline.indexers.opensearch_bulk import OpenSearchBulkIndexer
        indexer = OpenSearchBulkIndexer(opensearch_client=AsyncMock())
        actions = indexer._build_actions(
            sample_embedded_chunks, metadata_with_extras, "test-index", "chunk_embedding_test"
        )
        os_id = actions[0]["index"]["_id"]
        assert os_id.startswith("ext-doc-1_")


# ---------------------------------------------------------------------------
# Phase 2: init_composable_index
# ---------------------------------------------------------------------------


class TestInitComposableIndex:

    @pytest.fixture
    def pipeline_cfg(self):
        return PipelineConfig(
            ingestion_mode="composable",
            embedder=EmbedderConfig(provider="openai", model="text-embedding-3-small"),
        )

    @pytest.mark.asyncio
    @patch("pipeline.index_management.init_composable_index.__module__")
    async def test_creates_index_when_missing(self, _, pipeline_cfg, mock_opensearch_client):
        mock_opensearch_client.indices.exists = AsyncMock(return_value=False)
        mock_opensearch_client.indices.create = AsyncMock()

        with patch("utils.embeddings.create_dynamic_index_body", new_callable=AsyncMock, return_value={"mappings": {}}):
            with patch("utils.embedding_fields.ensure_embedding_field_exists", new_callable=AsyncMock):
                with patch("config.settings.get_index_name", return_value="test-index"):
                    with patch("config.settings.API_KEYS_INDEX_BODY", {"mappings": {}}):
                        with patch("config.settings.API_KEYS_INDEX_NAME", "api_keys"):
                            from pipeline.index_management import init_composable_index
                            result = await init_composable_index(mock_opensearch_client, pipeline_cfg)

        assert result == "test-index"
        assert mock_opensearch_client.indices.create.call_count == 3  # docs + kf + api_keys

    @pytest.mark.asyncio
    async def test_ensures_embedding_field_when_exists(self, pipeline_cfg, mock_opensearch_client):
        mock_opensearch_client.indices.exists = AsyncMock(side_effect=[True, True, True])
        mock_opensearch_client.indices.create = AsyncMock()

        with patch("utils.embeddings.create_dynamic_index_body", new_callable=AsyncMock, return_value={"mappings": {}}):
            with patch("utils.embedding_fields.ensure_embedding_field_exists", new_callable=AsyncMock) as mock_ensure:
                with patch("config.settings.get_index_name", return_value="test-index"):
                    with patch("config.settings.API_KEYS_INDEX_BODY", {"mappings": {}}):
                        with patch("config.settings.API_KEYS_INDEX_NAME", "api_keys"):
                            from pipeline.index_management import init_composable_index
                            await init_composable_index(mock_opensearch_client, pipeline_cfg)

        mock_ensure.assert_called_once_with(
            mock_opensearch_client, "text-embedding-3-small", "test-index"
        )
        mock_opensearch_client.indices.create.assert_not_called()


# ---------------------------------------------------------------------------
# Phase 5: ConnectorRouter composable routing
# ---------------------------------------------------------------------------


class TestConnectorRouterComposable:
    def test_composable_mode_routes_to_openrag(self):
        from api.connector_router import ConnectorRouter

        lf_svc = MagicMock(name="langflow_svc")
        or_svc = MagicMock(name="openrag_svc")
        cfg = PipelineConfig(ingestion_mode="composable")

        router = ConnectorRouter(lf_svc, or_svc, pipeline_config=cfg)
        assert router.get_active_service() is or_svc

    def test_traditional_mode_routes_to_langflow(self):
        from api.connector_router import ConnectorRouter

        lf_svc = MagicMock(name="langflow_svc")
        or_svc = MagicMock(name="openrag_svc")
        cfg = PipelineConfig(ingestion_mode="langflow")

        with patch("api.connector_router.DISABLE_INGEST_WITH_LANGFLOW", False):
            router = ConnectorRouter(lf_svc, or_svc, pipeline_config=cfg)
            assert router.get_active_service() is lf_svc

    def test_no_pipeline_config_falls_back(self):
        from api.connector_router import ConnectorRouter

        lf_svc = MagicMock(name="langflow_svc")
        or_svc = MagicMock(name="openrag_svc")

        with patch("api.connector_router.DISABLE_INGEST_WITH_LANGFLOW", True):
            router = ConnectorRouter(lf_svc, or_svc, pipeline_config=None)
            assert router.get_active_service() is or_svc


# ---------------------------------------------------------------------------
# Phase 7: PipelineConfig sync
# ---------------------------------------------------------------------------


class TestPipelineConfigSync:
    def test_sync_from_openrag_config(self):
        cfg = PipelineConfig(
            embedder=EmbedderConfig(provider="openai", model="text-embedding-3-small"),
        )
        openrag_cfg = MagicMock()
        openrag_cfg.knowledge.embedding_model = "ibm/slate-125m-english-rtrvr"
        openrag_cfg.knowledge.embedding_provider = "watsonx"

        cfg.sync_from_openrag_config(openrag_cfg)

        assert cfg.embedder.model == "ibm/slate-125m-english-rtrvr"
        assert cfg.embedder.provider == "watsonx"

    def test_sync_preserves_existing_when_empty(self):
        cfg = PipelineConfig(
            embedder=EmbedderConfig(provider="openai", model="text-embedding-3-small"),
        )
        openrag_cfg = MagicMock()
        openrag_cfg.knowledge.embedding_model = ""
        openrag_cfg.knowledge.embedding_provider = ""

        cfg.sync_from_openrag_config(openrag_cfg)

        assert cfg.embedder.model == "text-embedding-3-small"
        assert cfg.embedder.provider == "openai"
