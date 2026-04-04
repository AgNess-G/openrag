"""Rolling window conversation manager for the composable retrieval pipeline.

Delegates storage to existing agent.py functions — no new storage mechanism.
"""

from __future__ import annotations

from pipeline.retrieval.types import ConversationMessage
from utils.logging_config import get_logger

logger = get_logger(__name__)


class RollingWindowConversationManager:
    def __init__(self, rolling_window: int = 20) -> None:
        self.rolling_window = rolling_window

    async def get_history(
        self, user_id: str | None, previous_response_id: str | None
    ) -> list[ConversationMessage]:
        if not user_id or not previous_response_id:
            return []

        from agent import get_conversation_thread

        thread = get_conversation_thread(user_id, previous_response_id)
        if not thread:
            return []

        messages = thread.get("messages", [])
        converted = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role not in ("user", "assistant"):
                continue
            if not isinstance(content, str):
                continue
            converted.append(ConversationMessage(role=role, content=content))

        # Apply rolling window
        return converted[-self.rolling_window :]

    async def store(
        self,
        user_id: str | None,
        response_id: str,
        query_text: str,
        response_text: str,
        previous_response_id: str | None = None,
    ) -> None:
        if not user_id:
            return

        from datetime import datetime
        from agent import store_conversation_thread

        # Build minimal conversation state compatible with existing store function
        messages = [
            {
                "role": "system",
                "content": "You are the OpenRAG Agent.",
            },
            {
                "role": "user",
                "content": query_text,
            },
            {
                "role": "assistant",
                "content": response_text,
            },
        ]

        conversation_state = {
            "messages": messages,
            "previous_response_id": previous_response_id,
            "created_at": datetime.now(),
            "last_activity": datetime.now(),
        }

        await store_conversation_thread(user_id, response_id, conversation_state)
        logger.debug(
            "Stored conversation",
            user_id=user_id,
            response_id=response_id,
            rolling_window=self.rolling_window,
        )
