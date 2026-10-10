from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class UserAiSettings(Base):
    """Per-user in-app AI assistant configuration (doc/ai_integration/AI_ASSISTANT.md).

    One row per user. The API key is private to its owner: encrypted at rest and never
    returned by any endpoint. ``enabled`` is the user's master switch and is independent
    of the key. The two ``share_*`` flags are the opt-in data-sharing switches (default
    off): device-derived data may only reach the model when the user allowed it.
    """

    __tablename__ = "user_ai_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="anthropic")
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    api_key_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    share_inventory_data: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    share_content_data: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
