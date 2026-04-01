"""Core data models for the composable ingestion pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class FileMetadata:
    file_path: str
    filename: str
    file_hash: str
    file_size: int
    mimetype: str
    owner_user_id: str | None = None
    jwt_token: str | None = None
    connector_type: str = "local"
    acl: dict | None = None


@dataclass(slots=True)
class ParsedDocument:
    filename: str
    content: str
    mimetype: str
    pages: list[dict] | None = None
    tables: list[dict] | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class Chunk:
    text: str
    index: int
    source: str
    page: int | None = None
    chunk_type: str = "text"
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class EmbeddedChunk:
    text: str
    index: int
    source: str
    embedding: list[float] = field(repr=False)
    embedding_model: str = ""
    embedding_dimensions: int = 0
    page: int | None = None
    chunk_type: str = "text"
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class IndexResult:
    document_id: str
    chunks_indexed: int
    index_name: str
    status: str = "success"


@dataclass(slots=True)
class PipelineResult:
    file_path: str
    document_id: str
    filename: str
    chunks_total: int
    chunks_indexed: int
    status: str = "success"
    error: str | None = None
    duration_seconds: float = 0.0
