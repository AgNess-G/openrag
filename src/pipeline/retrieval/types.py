"""Core data models for the composable retrieval pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class SearchResult:
    text: str
    filename: str
    score: float
    page: int | None = None
    mimetype: str = ""
    source_url: str | None = None
    owner: str | None = None
    owner_name: str | None = None
    owner_email: str | None = None
    connector_type: str | None = None
    document_id: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class RetrievalQuery:
    text: str
    user_id: str | None = None
    jwt_token: str | None = None
    filters: dict | None = None
    limit: int = 10
    score_threshold: float = 0.0


@dataclass(slots=True)
class ConversationMessage:
    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: str | None = None


@dataclass(slots=True)
class AgentResponse:
    response: str
    response_id: str
    sources: list[SearchResult] = field(default_factory=list)
    usage: dict = field(default_factory=dict)  # {input_tokens, output_tokens, total_tokens}
