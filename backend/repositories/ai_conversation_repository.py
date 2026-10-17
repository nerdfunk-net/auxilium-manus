from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from core.models.ai_conversations import AiConversation
from repositories.updates import apply_updates

_UPDATABLE_FIELDS = frozenset({"title", "messages"})


class AiConversationRepository:
    """Every read and write is scoped to the owning ``user_id``: another user's row is simply
    not found."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_for_user(
        self, user_id: int, *, surface: str | None = None, subject_key: str | None = None
    ) -> list[AiConversation]:
        stmt = select(AiConversation).where(AiConversation.user_id == user_id)
        if surface is not None:
            stmt = stmt.where(AiConversation.surface == surface)
        if subject_key is not None:
            stmt = stmt.where(AiConversation.subject_key == subject_key)
        stmt = stmt.order_by(AiConversation.updated_at.desc(), AiConversation.id.desc())
        return list(self.db.scalars(stmt))

    def get_for_user(self, user_id: int, conversation_id: int) -> AiConversation | None:
        stmt = select(AiConversation).where(
            AiConversation.id == conversation_id, AiConversation.user_id == user_id
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def count_for_user(self, user_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(AiConversation)
            .where(AiConversation.user_id == user_id)
        )
        return int(self.db.execute(stmt).scalar_one())

    def create(
        self,
        user_id: int,
        *,
        surface: str,
        subject_key: str,
        title: str,
        messages: list[dict[str, Any]],
    ) -> AiConversation:
        row = AiConversation(
            user_id=user_id,
            surface=surface,
            subject_key=subject_key,
            title=title,
            messages=messages,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def update(self, row: AiConversation, values: Mapping[str, Any]) -> AiConversation:
        apply_updates(row, values, _UPDATABLE_FIELDS)
        # onupdate only fires when a column value changes; a re-save of identical messages
        # should still move the conversation to the top of the list.
        row.updated_at = func.now()
        self.db.commit()
        self.db.refresh(row)
        return row

    def delete(self, row: AiConversation) -> None:
        self.db.delete(row)
        self.db.commit()

    def purge_older_than(self, cutoff: datetime) -> int:
        result = self.db.execute(delete(AiConversation).where(AiConversation.updated_at < cutoff))
        self.db.commit()
        return int(getattr(result, "rowcount", 0) or 0)
