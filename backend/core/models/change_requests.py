from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ChangeRequest(Base):
    """A staged config change awaiting review before it is deployed to devices.

    Produced by the ``open-change-request`` workflow step at the end of a *stage
    run*: the rendered configs are committed to a per-change git branch
    (``branch``/``commit_sha``) and this row is written in ``status="staged"``.
    A reviewer (UI ``POST /change-requests/{id}/approve`` or a signed git
    webhook) then advances it; approval dispatches a separate *deploy run*
    (``deploy_run_id``). The review can take arbitrarily long because this row
    is the wait — no Hatchet task is suspended. See ``doc/CICD_PIPELINE.md``.

    ``status`` is a plain string (not ``sqlalchemy.Enum``) because
    ``AutoSchemaMigration`` has no Enum support — same rule as
    ``Credential.storage_backend``. The Pydantic layer carries the
    ``ChangeRequestStatus`` literal.
    """

    __tablename__ = "change_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)

    # The workflow + run that produced this change request.
    source_workflow_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_run_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # The workflow that deploys this change (pinned by the step config, or chosen
    # at approval time) and the run that actually did it.
    deploy_workflow_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True
    )
    deploy_run_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    git_repository_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("git_repositories.id", ondelete="SET NULL"), nullable=True
    )
    # Branch the CR forked from (the repo default at stage time).
    base_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Per-change branch the rendered configs were pushed to, e.g. ``manus/cr-42``.
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    # Commit that carries the rendered configs — the webhook correlation key.
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    title: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Captured from the stage run and replayed verbatim into the deploy run
    # (already validated at stage time — never re-resolved).
    device_ids: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    run_inputs: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )

    # Unified diff artifact (stored on the *stage run's* uuid).
    diff_artifact_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # {additions, deletions, files, truncated} — list badges + a truncation notice.
    diff_stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # staged | approved | deploying | deployed | failed | rejected | expired
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'staged'"), index=True
    )

    approved_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # ui | webhook
    approved_via: Mapped[str | None] = mapped_column(String(16), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    rejected_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Copied from a failed deploy run.
    deploy_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_change_requests_status", "status"),
        Index("idx_change_requests_repo_commit", "git_repository_id", "commit_sha"),
        # At most one in-flight change request per repo + commit — the stage step
        # relies on this to reject a duplicate render of the same commit.
        Index(
            "uq_change_requests_active_commit",
            "git_repository_id",
            "commit_sha",
            unique=True,
            postgresql_where=text("status in ('staged', 'approved', 'deploying')"),
        ),
    )
