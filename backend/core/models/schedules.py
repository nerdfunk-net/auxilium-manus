from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class WorkflowSchedule(Base):
    __tablename__ = "workflow_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    # NOT unique — a workflow may carry many schedules (e.g. one per site /
    # inventory, each with its own run_inputs). The legacy UNIQUE constraint is
    # dropped by a one-off ALTER (see doc/SCHEDULES.md); AutoSchemaMigration does
    # not drop constraints.
    workflow_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Operator-facing label, unique only by convention within a workflow.
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Per-schedule static-attribute values, merged with the workflow's declared
    # defaults at dispatch by resolve_run_inputs(). Shape-validated at save time;
    # `reference` values additionally checked against the target row for
    # created_by (see services/execution/reference_resolver.py).
    run_inputs: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    # cron | once
    schedule_type: Mapped[str] = mapped_column(String(10), nullable=False)
    cron_expression: Mapped[str | None] = mapped_column(String(120), nullable=True)
    run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # External Hatchet reference for delete/update, whichever applies to schedule_type.
    hatchet_cron_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hatchet_scheduled_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
