from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class AiGlossaryTerm(Base):
    """One word of local vocabulary ("core", "DC") the inventory assistant may expand into a filter.

    Global and admin-managed (doc/ai_integration/AI_ASSISTANT.md, "Glossary"). ``filter`` holds the
    ``FilterInput`` shape; ``note`` is for administrators only and is never sent to the model.
    ``term_key`` is the lower-cased term (unique); alias uniqueness is checked by the service.
    ``search_text`` is the lower-cased term plus aliases, for the admin search box.
    """

    __tablename__ = "ai_glossary_terms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    term: Mapped[str] = mapped_column(String(64), nullable=False)
    term_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    aliases: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    search_text: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    filter: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AiGlossaryName(Base):
    """Every folded name (the term and each alias) of an entry, one row each.

    The unique index makes "a word means one thing" a database rule, so two concurrent saves
    cannot both claim the same word. Rows are written and removed together with their term.
    """

    __tablename__ = "ai_glossary_names"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    term_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ai_glossary_terms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
