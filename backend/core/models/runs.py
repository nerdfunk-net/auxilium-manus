from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    workflow_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    triggered_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # pending | running | paused | success | failed | cancelled
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    # manual | scheduled | webhook
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    # normal | debug
    run_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    # node_id awaiting the next step/continue action while status == "paused"
    current_node_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # latest engine-authored narration for debug-mode pauses/resumes
    debug_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Wait & Run: populated while a fan-out run is between approval batches.
    # None on non-approval runs and cleared when the run reaches a terminal status.
    approval_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    device_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Resolved values for the workflow's declared static_attributes (defaults
    # filled in) at the time this run was triggered.
    run_inputs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    hatchet_run_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    # Set when this run is a *deploy run* dispatched by a ChangeRequest approval
    # (see doc/CICD_PIPELINE.md). Drives status reconciliation and the
    # use_change_request_branch override on git-pull/git-clone.
    #
    # change_requests.source_run_id/deploy_run_id reference workflow_runs.id,
    # so this column's FK back to change_requests.id forms a table-level
    # cycle. use_alter=True (with an explicit name, required by every
    # dialect's ALTER TABLE ADD CONSTRAINT) tells SQLAlchemy to emit this
    # constraint separately, after both tables exist, instead of inline in
    # CREATE TABLE — see AutoSchemaMigration.create_missing_tables.
    change_request_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "change_requests.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_workflow_runs_change_request_id",
        ),
        nullable=True,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # configuration | execution | internal — see step_runner.classify_step_exception
    error_category: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # correlates this failure with the full traceback in worker logs
    error_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class WorkflowStepResult(Base):
    __tablename__ = "workflow_step_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_node_id: Mapped[str] = mapped_column(String(255), nullable=False)
    step_type: Mapped[str] = mapped_column(String(100), nullable=False)
    step_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # pending | running | success | partial | failed | skipped
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # configuration | execution | internal — see step_runner.classify_step_exception
    error_category: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # correlates this failure with the full traceback in worker logs
    error_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
