from __future__ import annotations

import uuid as uuid_mod
from typing import Any, cast

from sqlalchemy import CursorResult, or_, select, update
from sqlalchemy.orm import Session

from core.models.users import User
from core.models.workflows import Workflow
from repositories.updates import apply_updates

_UPDATABLE_FIELDS = frozenset(
    {
        "name",
        "description",
        "folder",
        "visibility",
        "canvas_nodes",
        "canvas_edges",
        "canvas_groups",
        "static_attributes",
        "is_version_controlled",
        "notes",
    }
)


def _same_id(value: Any, template_id: int) -> bool:
    try:
        return int(value) == template_id
    except (TypeError, ValueError):
        return False


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
        static_attributes: list[dict[str, Any]] | None = None,
        is_version_controlled: bool = False,
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
            static_attributes=static_attributes or [],
            is_version_controlled=is_version_controlled,
        )
        self.db.add(workflow)
        self.db.commit()
        self.db.refresh(workflow)
        return workflow

    def update(self, workflow: Workflow, fields: dict[str, Any]) -> Workflow:
        apply_updates(workflow, fields, _UPDATABLE_FIELDS)
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

    def template_is_referenced(self, template_id: int) -> bool:
        """True when any workflow has a render-jinja-template node using ``template_id``.

        A Python-side scan of the stored canvases; the table is small."""
        for nodes in self.db.scalars(select(Workflow.canvas_nodes)):
            for node in nodes or []:
                data = node.get("data") if isinstance(node, dict) else None
                if not isinstance(data, dict) or data.get("kind") != "render-jinja-template":
                    continue
                config = data.get("pluginConfig") or {}
                if isinstance(config, dict) and _same_id(config.get("template_id"), template_id):
                    return True
        return False

    def reassign_creator(self, from_user_id: int, to_user_id: int) -> int:
        """Hand a deleted user's workflows to ``to_user_id``. Executes within the open
        transaction without committing; the caller commits with the user deletion."""
        result = self.db.execute(
            update(Workflow)
            .where(Workflow.creator_id == from_user_id)
            .values(creator_id=to_user_id)
        )
        return cast(CursorResult, result).rowcount or 0

    def delete(self, workflow: Workflow) -> None:
        self.db.delete(workflow)
        self.db.commit()
