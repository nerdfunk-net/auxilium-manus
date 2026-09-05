from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class WorkflowChange(Base):
    """One row per workflow save (create/update) — the DB-level audit trail.

    Independent of Git-backed versioning (``Workflow.is_version_controlled``):
    an entry is written on every save regardless, but ``commit_sha`` /
    ``parent_commit_sha`` are only populated when that save also produced a
    successful git commit, which is what lets the "Changes" UI offer a diff
    for that entry.
    """

    __tablename__ = "workflow_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Denormalized snapshot so the log stays readable after the user is
    # deleted — mirrors the actor_username baked into git commit messages by
    # WorkflowGitService._sync.
    actor_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
