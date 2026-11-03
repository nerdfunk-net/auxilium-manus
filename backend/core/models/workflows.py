from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
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
    # Free-form markdown wiki notes, edited independently of the canvas save
    # path (see WorkflowService.update_notes) — never synced to git.
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    folder: Mapped[str | None] = mapped_column(String(500), nullable=True, default="/")
    visibility: Mapped[str] = mapped_column(String(10), nullable=False, default="private")
    canvas_nodes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    canvas_edges: Mapped[list | None] = mapped_column(JSON, nullable=True)
    canvas_groups: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Schema of run-scoped trigger inputs (name/type/default/required); values
    # supplied at trigger time are seeded into every device's attribute_bags
    # under the "run_input" bag — see services/workflow_context/run_inputs.py.
    static_attributes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_version_controlled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Release for the Ask the Net assistant (doc/AI_TOOL_CHAIN.md section 16). Cleared by any
    # edit of the definition (D7), so a release always refers to the reviewed version.
    ai_released: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ai_released_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    ai_released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # What the workflow does, when to use it, what each input means, what the result holds.
    ai_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The one step node whose output the assistant may read as the result.
    ai_result_node_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # The text run input that receives the device lines (read by a Get from User step), the
    # credential run inputs the confirming user fills in, and whether the assistant may pass an
    # IPv4 address that is not in the inventory. Released with, and cleared with, the rest.
    ai_devices_input: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ai_credential_inputs: Mapped[list | None] = mapped_column(JSON, nullable=True)
    ai_allow_free_ip: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Hash of the released definition, its release settings and every workflow it starts
    # (services/workflow/release_stamp.py). A release counts only while it still matches.
    ai_release_stamp: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
