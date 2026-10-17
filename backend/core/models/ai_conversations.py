from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class AiConversation(Base):
    """A conversation the user saved from the in-app AI assistant panel
    (doc/ai_integration/AI_ASSISTANT.md, "Sessions and saved conversations").

    Private to ``user_id``. ``messages`` holds the redacted display messages (text, tool chips,
    a proposal summary) - never a full proposal payload, since a stored canvas would be stale on
    resume. ``subject_key`` says what the chat was about (a workflow or template id, a source id,
    or empty), matching the panel's session key.
    """

    __tablename__ = "ai_conversations"
    __table_args__ = (
        Index("ix_ai_conversations_user_surface", "user_id", "surface", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    surface: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    messages: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        index=True,
    )
