"""LangChain LCEL chain for nudges (follow-up suggestion) generation."""

from __future__ import annotations

from pipeline.retrieval.types import ConversationMessage, RetrievalQuery
from utils.logging_config import get_logger

logger = get_logger(__name__)

try:
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_openai import ChatOpenAI

    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

_NUDGES_SYSTEM = """You are a helpful assistant generating follow-up question suggestions.
Based on the retrieved context and conversation history provided, generate {max_suggestions} concise,
distinct follow-up questions that the user might want to ask next.

Rules:
- Each suggestion must be a complete, standalone question
- Questions should be specific and answerable from the knowledge base
- Do not repeat questions already asked in the conversation
- Output ONLY the questions, one per line, no numbering or bullets
"""

_NUDGES_HUMAN = """Retrieved context:
{context}

Conversation history:
{history}

Generate {max_suggestions} follow-up questions:"""


class LangChainNudgesGenerator:
    def __init__(
        self,
        model: str = "gpt-4o-mini",
        provider: str = "openai",
        max_suggestions: int = 5,
        temperature: float = 0.5,
        **_kwargs,
    ) -> None:
        if not _AVAILABLE:
            raise ImportError(
                "langchain and langchain-openai are required for LangChainNudgesGenerator. "
                "Install with: pip install langchain langchain-openai"
            )
        self.model = model
        self.provider = provider
        self.max_suggestions = max_suggestions
        self.temperature = temperature

    def _build_chain(self):
        llm = ChatOpenAI(model=self.model, temperature=self.temperature)
        prompt = ChatPromptTemplate.from_messages([
            ("system", _NUDGES_SYSTEM),
            ("human", _NUDGES_HUMAN),
        ])
        return prompt | llm | StrOutputParser()

    async def generate(
        self,
        query: RetrievalQuery,
        history: list[ConversationMessage],
    ) -> list[str]:
        # Retrieve context relevant to the conversation
        try:
            from pipeline.retrieval.retrievers.opensearch_hybrid import HybridRetriever

            # Build context from conversation to search against
            search_text = query.text or _build_history_summary(history)
            if not search_text:
                return []

            retriever = HybridRetriever()
            search_query = RetrievalQuery(
                text=search_text,
                user_id=query.user_id,
                jwt_token=query.jwt_token,
                filters=query.filters,
                limit=5,
            )
            docs = await retriever.retrieve(search_query)
            context = "\n\n".join(
                f"[{i+1}] {d.filename}: {d.text[:400]}" for i, d in enumerate(docs)
            )
        except Exception as e:
            logger.warning("NudgesGenerator: retrieval failed, using empty context", error=str(e))
            context = ""

        history_str = "\n".join(
            f"{m.role}: {m.content}" for m in history if m.role in ("user", "assistant")
        )

        chain = self._build_chain()
        try:
            raw = await chain.ainvoke({
                "context": context or "No context retrieved.",
                "history": history_str or "No conversation history.",
                "max_suggestions": self.max_suggestions,
            })
        except Exception as e:
            logger.error("NudgesGenerator: LLM call failed", error=str(e))
            return []

        suggestions = [line.strip() for line in raw.strip().splitlines() if line.strip()]
        return suggestions[: self.max_suggestions]


def _build_history_summary(history: list[ConversationMessage]) -> str:
    """Extract last user message from history to use as search query."""
    for msg in reversed(history):
        if msg.role == "user":
            return msg.content
    return ""
