"""Composable retrieval pipeline orchestrator and builder."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict
from typing import TYPE_CHECKING, AsyncIterator

from pipeline.retrieval.types import AgentResponse, RetrievalQuery
from utils.logging_config import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:
    from pipeline.retrieval.agents.base import Agent
    from pipeline.retrieval.config import RetrievalConfig
    from pipeline.retrieval.conversation import RollingWindowConversationManager
    from pipeline.retrieval.nudges.base import NudgesGenerator
    from pipeline.retrieval.rerankers.base import Reranker
    from pipeline.retrieval.registry import RetrievalRegistry
    from pipeline.retrieval.retrievers.base import Retriever


class RetrievalPipeline:
    """Runs the full retrieve → rerank → agent flow."""

    def __init__(
        self,
        retriever: Retriever,
        reranker: Reranker,
        agent: Agent,
        nudges_generator: NudgesGenerator,
        conversation_manager: RollingWindowConversationManager,
        config: RetrievalConfig,
    ) -> None:
        self.retriever = retriever
        self.reranker = reranker
        self.agent = agent
        self.nudges_generator = nudges_generator
        self.conversation_manager = conversation_manager
        self.config = config

    async def run(
        self,
        query: RetrievalQuery,
        previous_response_id: str | None = None,
    ) -> AgentResponse:
        start = time.monotonic()

        def _elapsed() -> float:
            return round(time.monotonic() - start, 2)

        label = (query.text or "")[:60]

        try:
            # Load rolling window conversation history
            history = await self.conversation_manager.get_history(
                query.user_id, previous_response_id
            )
            logger.info(
                "RetrievalPipeline: history loaded",
                user_id=query.user_id,
                history_messages=len(history),
            )

            # Retrieve relevant documents
            logger.info(
                "RetrievalPipeline: retrieve",
                query=label,
                retriever=type(self.retriever).__name__,
            )
            results = await self.retriever.retrieve(query)
            logger.info(
                "RetrievalPipeline: retrieve done",
                results_count=len(results),
                elapsed_s=_elapsed(),
            )

            # Rerank results
            logger.info(
                "RetrievalPipeline: rerank",
                reranker=type(self.reranker).__name__,
                input_count=len(results),
            )
            results = await self.reranker.rerank(query.text, results)
            logger.info(
                "RetrievalPipeline: rerank done",
                output_count=len(results),
                elapsed_s=_elapsed(),
            )

            # Run agent
            logger.info(
                "RetrievalPipeline: agent",
                agent=type(self.agent).__name__,
            )
            response = await self.agent.run(query.text, results, history, user_id=query.user_id, jwt_token=query.jwt_token)
            logger.info(
                "RetrievalPipeline: agent done",
                response_id=response.response_id,
                elapsed_s=_elapsed(),
            )

            # Store conversation for future turns
            await self.conversation_manager.store(
                user_id=query.user_id,
                response_id=response.response_id,
                query_text=query.text,
                response_text=response.response,
                previous_response_id=previous_response_id,
            )

            return response

        except Exception as exc:
            logger.error(
                "RetrievalPipeline: exception",
                query=label,
                error=str(exc),
                error_type=type(exc).__name__,
                elapsed_s=_elapsed(),
            )
            raise

    async def run_stream(
        self,
        query: RetrievalQuery,
        previous_response_id: str | None = None,
    ) -> AsyncIterator[str]:
        """Retrieve → rerank → stream agent tokens as newline-delimited JSON.

        Yields:
            ``{"delta": "<token>"}`` lines during generation.
            A final ``{"response_id": "...", "sources": [...], "usage": {}}`` line.
        """
        # Load history
        history = await self.conversation_manager.get_history(
            query.user_id, previous_response_id
        )

        # Retrieve + rerank (non-streaming — must complete before agent starts)
        results = await self.retriever.retrieve(query)
        results = await self.reranker.rerank(query.text, results)

        logger.info(
            "RetrievalPipeline.run_stream: starting",
            retriever=type(self.retriever).__name__,
            agent=type(self.agent).__name__,
            results_count=len(results),
        )

        # Stream agent tokens
        response_text = ""
        usage: dict = {}
        if not hasattr(self.agent, "run_stream"):
            # Fallback: agents that don't support streaming yet
            response = await self.agent.run(query.text, results, history, user_id=query.user_id, jwt_token=query.jwt_token)
            response_text = response.response
            yield json.dumps({"delta": response.response}) + "\n"
            response_id = response.response_id
            sources = results
            usage = response.usage
        else:
            response_id = str(uuid.uuid4())
            sources = results
            async for chunk in self.agent.run_stream(query.text, results, history, user_id=query.user_id, jwt_token=query.jwt_token):
                # Each chunk is a JSON line; forward it to the client unchanged,
                # but also accumulate response_text and usage for conversation storage.
                yield chunk
                try:
                    data = json.loads(chunk.strip())
                    if "delta" in data:
                        response_text += data["delta"]
                    elif data.get("type") == "response.completed":
                        usage = data.get("response", {}).get("usage", {})
                except (json.JSONDecodeError, AttributeError):
                    pass

        # Store conversation
        await self.conversation_manager.store(
            user_id=query.user_id,
            response_id=response_id,
            query_text=query.text,
            response_text=response_text,
            previous_response_id=previous_response_id,
        )

        # Emit final metadata chunk
        yield json.dumps({
            "response_id": response_id,
            "sources": [
                {
                    "filename": s.filename,
                    "text": s.text,
                    "score": s.score,
                    "page": s.page,
                    "mimetype": s.mimetype,
                    "source_url": s.source_url,
                    "owner_name": s.owner_name,
                    "connector_type": s.connector_type,
                }
                for s in sources
            ],
            "usage": usage,
        }) + "\n"

    async def generate_nudges(
        self,
        query: RetrievalQuery,
        previous_response_id: str | None = None,
    ) -> list[str]:
        history = await self.conversation_manager.get_history(query.user_id, previous_response_id)
        return await self.nudges_generator.generate(query, history)

    def to_response_dict(self, response: AgentResponse) -> dict:
        """Convert AgentResponse to the API response format."""
        sources = []
        for s in response.sources:
            sources.append({
                "filename": s.filename,
                "text": s.text,
                "score": s.score,
                "page": s.page,
                "mimetype": s.mimetype,
                "source_url": s.source_url,
                "owner": s.owner,
                "owner_name": s.owner_name,
                "owner_email": s.owner_email,
                "connector_type": s.connector_type,
            })
        return {
            "response": response.response,
            "response_id": response.response_id,
            "sources": sources,
            "usage": response.usage,
        }


class RetrievalPipelineBuilder:
    """Construct a RetrievalPipeline from config + registry."""

    def __init__(self, config: RetrievalConfig, registry: RetrievalRegistry) -> None:
        self._config = config
        self._registry = registry

    def build(self, opensearch_client=None) -> RetrievalPipeline:
        retriever = self._build_retriever(opensearch_client)
        reranker = self._build_reranker()
        agent = self._build_agent()
        nudges_gen = self._build_nudges()
        conv_mgr = self._build_conversation_manager()
        return RetrievalPipeline(retriever, reranker, agent, nudges_gen, conv_mgr, self._config)

    def _build_retriever(self, opensearch_client=None):
        cfg = self._config.retriever
        cls = self._registry.get(cfg.type, "retriever")
        kwargs = {}
        if cfg.type == "hybrid":
            kwargs = {
                "semantic_weight": cfg.semantic_weight,
                "keyword_weight": cfg.keyword_weight,
                "tie_breaker": cfg.tie_breaker,
            }
        if opensearch_client:
            kwargs["opensearch_client"] = opensearch_client
        return cls(**kwargs)

    def _build_reranker(self):
        cfg = self._config.reranker
        cls = self._registry.get(cfg.type, "reranker")
        if cfg.type == "none":
            return cls()
        kwargs = {"top_k": cfg.top_k}
        if cfg.type == "cohere":
            kwargs["model"] = cfg.cohere.model
        elif cfg.type == "cross_encoder":
            kwargs["model"] = cfg.cross_encoder_model
        return cls(**kwargs)

    def _build_agent(self):
        cfg = self._config.agent
        cls = self._registry.get(cfg.type, "agent")
        return cls(
            model=cfg.model,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            system_prompt=cfg.system_prompt,
            max_iterations=cfg.max_iterations,
            tools=cfg.tools,
        )

    def _build_nudges(self):
        cfg = self._config.nudges
        if not cfg.enabled:
            from pipeline.retrieval.nudges.none import PassthroughNudgesGenerator
            return PassthroughNudgesGenerator()
        cls = self._registry.get(cfg.type, "nudges")
        return cls(
            model=cfg.model,
            provider=cfg.provider,
            max_suggestions=cfg.max_suggestions,
            temperature=cfg.temperature,
        )

    def _build_conversation_manager(self):
        from pipeline.retrieval.conversation import RollingWindowConversationManager
        return RollingWindowConversationManager(
            rolling_window=self._config.conversation.rolling_window
        )


class RetrievalPipelineManager:
    """Singleton manager for the retrieval pipeline."""

    _instance: RetrievalPipeline | None = None

    @classmethod
    def get_pipeline(cls, opensearch_client=None) -> RetrievalPipeline:
        if cls._instance is None:
            cls._instance = cls._build_pipeline(opensearch_client)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Force pipeline rebuild on next get_pipeline() call."""
        cls._instance = None

    @staticmethod
    def _build_pipeline(opensearch_client=None) -> RetrievalPipeline:
        from pipeline.retrieval.config import RetrievalConfigManager
        from pipeline.retrieval.registry import get_default_registry

        config = RetrievalConfigManager().get_config()
        registry = get_default_registry()
        builder = RetrievalPipelineBuilder(config, registry)
        return builder.build(opensearch_client)
