"""Saved AI assistant conversations: explicit "Save" from the panel, resume later.

The server chat stays stateless; a saved conversation is plain data the client loads back into
its session and re-sends as history. Stored text is run through the redactor first (user
messages can contain pasted secrets, and answers can echo tool output), so a stored
conversation never holds more than the model was shown. Proposals keep only kind and summary.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from core.models.ai_conversations import AiConversation
from models.ai_conversations import (
    MAX_CONVERSATION_CHARS,
    MAX_CONVERSATIONS_PER_USER,
    AiConversationCreate,
    AiConversationDetail,
    AiConversationSummary,
    AiConversationUpdate,
    StoredMessage,
)
from repositories.ai_conversation_repository import AiConversationRepository
from services.ai_assistant.exceptions import (
    AiConversationLimitError,
    AiConversationNotFoundError,
    AiConversationTooLargeError,
)
from services.ai_assistant.redaction import Redactor

logger = logging.getLogger(__name__)

_TITLE_CHARS = 80
_DEFAULT_TITLE = "Conversation"


def _redact_message(message: StoredMessage, redactor: Redactor) -> StoredMessage:
    return message.model_copy(
        update={
            "content": redactor.redact(message.content),
            "error": redactor.redact(message.error) if message.error else message.error,
            "proposal": (
                message.proposal.model_copy(
                    update={"summary": redactor.redact(message.proposal.summary)}
                )
                if message.proposal
                else None
            ),
        }
    )


def _default_title(messages: list[StoredMessage]) -> str:
    first = next((m.content for m in messages if m.role == "user" and m.content.strip()), "")
    collapsed = " ".join(first.split())
    return collapsed[:_TITLE_CHARS] or _DEFAULT_TITLE


def _summary(row: AiConversation) -> AiConversationSummary:
    return AiConversationSummary(
        id=row.id,
        surface=row.surface,  # type: ignore[arg-type]
        subject_key=row.subject_key,
        title=row.title,
        message_count=len(row.messages),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _detail(row: AiConversation) -> AiConversationDetail:
    return AiConversationDetail(
        **_summary(row).model_dump(),
        messages=[StoredMessage.model_validate(m) for m in row.messages],
    )


class AiConversationService:
    def __init__(self, repo: AiConversationRepository) -> None:
        self.repo = repo

    @classmethod
    def from_session(cls, db: Session) -> AiConversationService:
        return cls(AiConversationRepository(db))

    def list(
        self, user_id: int, *, surface: str | None, subject_key: str | None
    ) -> list[AiConversationSummary]:
        rows = self.repo.list_for_user(user_id, surface=surface, subject_key=subject_key)
        return [_summary(row) for row in rows]

    def get(self, user_id: int, conversation_id: int) -> AiConversationDetail:
        return _detail(self._require(user_id, conversation_id))

    def create(self, user_id: int, data: AiConversationCreate) -> AiConversationDetail:
        if self.repo.count_for_user(user_id) >= MAX_CONVERSATIONS_PER_USER:
            raise AiConversationLimitError(
                f"You can keep at most {MAX_CONVERSATIONS_PER_USER} saved conversations; "
                "delete one first"
            )
        messages = self._prepare(data.messages)
        redactor = Redactor()
        title = redactor.redact((data.title or "").strip()) or _default_title(messages)
        row = self.repo.create(
            user_id,
            surface=data.surface,
            subject_key=data.subject_key,
            title=title[:200],
            messages=messages_to_json(messages),
        )
        return _detail(row)

    def update(
        self, user_id: int, conversation_id: int, data: AiConversationUpdate
    ) -> AiConversationDetail:
        row = self._require(user_id, conversation_id)
        values: dict[str, object] = {}
        if data.title is not None:
            values["title"] = Redactor().redact(data.title.strip())[:200] or row.title
        if data.messages is not None:
            values["messages"] = messages_to_json(self._prepare(data.messages))
        return _detail(self.repo.update(row, values))

    def delete(self, user_id: int, conversation_id: int) -> None:
        self.repo.delete(self._require(user_id, conversation_id))

    def purge_older_than_days(self, days: int) -> int:
        """Retention sweep; ``days < 1`` keeps everything."""
        if days < 1:
            return 0
        deleted = self.repo.purge_older_than(datetime.now(UTC) - timedelta(days=days))
        logger.info("Purged %s saved AI conversation(s) older than %s day(s)", deleted, days)
        return deleted

    def _require(self, user_id: int, conversation_id: int) -> AiConversation:
        row = self.repo.get_for_user(user_id, conversation_id)
        if row is None:
            raise AiConversationNotFoundError("Saved conversation not found")
        return row

    @staticmethod
    def _prepare(messages: list[StoredMessage]) -> list[StoredMessage]:
        redactor = Redactor()
        prepared = [_redact_message(m, redactor) for m in messages]
        size = len(json.dumps([m.model_dump() for m in prepared]))
        if size > MAX_CONVERSATION_CHARS:
            raise AiConversationTooLargeError(
                "This conversation is too large to save; clear older messages first"
            )
        return prepared


def messages_to_json(messages: list[StoredMessage]) -> list[dict[str, object]]:
    return [m.model_dump(mode="json") for m in messages]
