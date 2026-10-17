"""Read-only queries for what refers to a credential (O1-04).

References are by name or id with no foreign key, so each kind of dependant is looked up
here. Every method returns ``(id, name)`` pairs (or settings ``(key, value)`` pairs) and never
a secret.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models.git import GitRepository
from core.models.secret_manager import SecretManagerConnection
from core.models.settings import Setting
from core.models.templates import Template
from core.models.workflows import Workflow


class CredentialUsageRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def git_repositories_using(self, credential_name: str) -> list[tuple[int, str]]:
        stmt = (
            select(GitRepository.id, GitRepository.name)
            .where(GitRepository.credential_name == credential_name)
            .order_by(GitRepository.id)
        )
        return [(row[0], row[1]) for row in self.db.execute(stmt)]

    def secret_managers_using(self, credential_name: str) -> list[tuple[int, str]]:
        stmt = (
            select(SecretManagerConnection.id, SecretManagerConnection.name)
            .where(SecretManagerConnection.credential_name == credential_name)
            .order_by(SecretManagerConnection.id)
        )
        return [(row[0], row[1]) for row in self.db.execute(stmt)]

    def templates_using(self, credential_id: int) -> list[tuple[int, str]]:
        stmt = (
            select(Template.id, Template.name)
            .where(Template.credential_id == credential_id)
            .order_by(Template.id)
        )
        return [(row[0], row[1]) for row in self.db.execute(stmt)]

    def settings_values(self) -> list[tuple[int, str, dict[str, Any]]]:
        """Every settings row as ``(id, key, value)``; source and mail rows carry the reference."""
        stmt = select(Setting.id, Setting.key, Setting.value).order_by(Setting.key)
        return [
            (row[0], row[1], row[2]) for row in self.db.execute(stmt) if isinstance(row[2], dict)
        ]

    def workflow_canvases(self) -> list[tuple[int, str, int | None, list[Any]]]:
        """``(id, name, creator_id, canvas_nodes)`` of every workflow; a Python-side scan of a
        small table, like ``WorkflowRepository.template_is_referenced``."""
        stmt = select(
            Workflow.id, Workflow.name, Workflow.creator_id, Workflow.canvas_nodes
        ).order_by(Workflow.id)
        return [(row[0], row[1], row[2], list(row[3] or [])) for row in self.db.execute(stmt)]
