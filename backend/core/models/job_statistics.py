from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class JobStatistic(Base):
    __tablename__ = "job_statistics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # Denormalized snapshot columns — captured at write time so history
    # survives a workflow rename. Not a second FK on workflow_id:
    # workflow_runs already cascades from workflows.id, so deleting a
    # workflow cascades workflow_runs -> job_statistics via run_id for free.
    workflow_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    workflow_name: Mapped[str] = mapped_column(String(255), nullable=False)
    device_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # success | failed — recorded verbatim from the node's `result` config,
    # never inferred from DeviceStatus. See doc/WORKFLOW-STEPS.md's
    # collect-statistics entry for why.
    result: Mapped[str] = mapped_column(String(10), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
