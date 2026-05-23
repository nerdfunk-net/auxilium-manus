from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str | None] = mapped_column(String(36), unique=True, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    creator_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    folder: Mapped[str | None] = mapped_column(String(500), nullable=True, default="/")
    visibility: Mapped[str] = mapped_column(String(10), nullable=False, default="private")
    canvas_nodes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    canvas_edges: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
