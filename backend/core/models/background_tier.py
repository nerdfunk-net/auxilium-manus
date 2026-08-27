from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class WorkflowBackgroundTier(Base):
    __tablename__ = "workflow_background_tier"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    workflow_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    # Generated once at first publish as f"WorkflowBackground-{workflow_id}" and never
    # changed afterwards, so the Hatchet-side workflow definition identity never drifts
    # under a rename or republish.
    hatchet_workflow_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    # None => unlimited (same as WorkflowExecution today). Passed straight through as
    # `concurrency=` to hatchet.workflow() by the dynamic worker.
    concurrency_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
