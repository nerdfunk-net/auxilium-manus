from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Denormalized snapshot columns — captured at write time so history
    # survives a workflow rename. Not a second FK on workflow_id:
    # workflow_runs already cascades from workflows.id, so deleting a
    # workflow cascades workflow_runs -> notifications via run_id for free.
    workflow_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    workflow_name: Mapped[str] = mapped_column(String(255), nullable=False)
    workflow_owner_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    device_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # info | warning | error
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="info", index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
