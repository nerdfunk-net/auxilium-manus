from __future__ import annotations

import uuid as uuid_mod
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from core.models.users import User
from core.models.workflows import Workflow


class WorkflowRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, workflow_id: int) -> tuple[Workflow, str | None] | None:
        stmt = (
            select(Workflow, User.username.label("creator_username"))
            .outerjoin(User, Workflow.creator_id == User.id)
            .where(Workflow.id == workflow_id)
        )
        row = self.db.execute(stmt).first()
        if row is None:
            return None
        return (row.Workflow, row.creator_username)

    def list_accessible(self, user_id: int) -> list[tuple[Workflow, str | None]]:
        stmt = (
            select(Workflow, User.username.label("creator_username"))
            .outerjoin(User, Workflow.creator_id == User.id)
            .where(
                or_(
                    Workflow.visibility == "public",
                    Workflow.creator_id == user_id,
                )
            )
            .order_by(Workflow.updated_at.desc())
        )
        return [(row.Workflow, row.creator_username) for row in self.db.execute(stmt)]

    def create(
        self,
        *,
        name: str,
        creator_id: int,
        description: str | None,
        folder: str | None,
        visibility: str,
        canvas_nodes: list[dict[str, Any]] | None,
        canvas_edges: list[dict[str, Any]] | None,
        canvas_groups: list[dict[str, Any]] | None = None,
    ) -> Workflow:
        workflow = Workflow(
            uuid=str(uuid_mod.uuid4()),
            name=name,
            creator_id=creator_id,
            description=description,
            folder=folder or "/",
            visibility=visibility,
            canvas_nodes=canvas_nodes or [],
            canvas_edges=canvas_edges or [],
            canvas_groups=canvas_groups or [],
        )
        self.db.add(workflow)
        self.db.commit()
        self.db.refresh(workflow)
        return workflow

    def update(self, workflow: Workflow, fields: dict[str, Any]) -> Workflow:
        for key, value in fields.items():
            setattr(workflow, key, value)
        self.db.commit()
        self.db.refresh(workflow)
        return workflow

    def name_exists(
        self,
        *,
        name: str,
        folder: str,
        visibility: str,
        creator_id: int,
        exclude_id: int | None = None,
    ) -> bool:
        """Check uniqueness: public workflows are globally unique by (name, folder),
        private workflows are unique per creator by (name, folder, creator_id)."""
        stmt = select(Workflow.id).where(
            Workflow.name == name,
            Workflow.folder == (folder or "/"),
            Workflow.visibility == visibility,
        )
        if visibility == "private":
            stmt = stmt.where(Workflow.creator_id == creator_id)
        if exclude_id is not None:
            stmt = stmt.where(Workflow.id != exclude_id)
        return self.db.execute(stmt).first() is not None

    def find_id_by_name(
        self,
        *,
        name: str,
        folder: str,
        visibility: str,
        creator_id: int,
    ) -> int | None:
        """Return the ID of a matching workflow, or None if not found.
        Follows the same uniqueness rules as name_exists."""
        stmt = select(Workflow.id).where(
            Workflow.name == name,
            Workflow.folder == (folder or "/"),
            Workflow.visibility == visibility,
        )
        if visibility == "private":
            stmt = stmt.where(Workflow.creator_id == creator_id)
        row = self.db.execute(stmt).first()
        return row[0] if row else None

    def delete(self, workflow: Workflow) -> None:
        self.db.delete(workflow)
        self.db.commit()
