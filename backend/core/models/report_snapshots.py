from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ReportSnapshot(Base):
    """An immutable, generated copy of a report: its definition plus every section's result.

    Survives deletion of its definition (``definition_id`` becomes NULL) because the
    definition is copied into ``content``. ``generated_by`` is a username, kept as text so the
    snapshot still says who generated it after the user is deleted.
    """

    __tablename__ = "report_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    definition_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("report_definitions.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    generated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # "complete": every section ran. "partial": at least one section failed (see its error).
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_report_snapshots_definition", "definition_id", "generated_at"),
        Index("idx_report_snapshots_generated_at", "generated_at"),
    )
