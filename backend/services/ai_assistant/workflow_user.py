"""The service user the ``contact-the-ai`` workflow step runs as (W10-12).

The operator names it with ``WORKFLOW_AI_USER``; its AI key, provider and sharing switches decide
what a workflow prompt may contain. A name that is unset, unknown or inactive makes the AI
unavailable to workflows.
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy.orm import Session

from repositories.user_repository import UserRepository


class WorkflowAiUserError(Exception):
    """The workflow AI user cannot be used; ``reason`` says why (no text from the database)."""

    def __init__(self, reason: Literal["not_set", "not_active"]) -> None:
        super().__init__(reason)
        self.reason = reason


def resolve_workflow_user_id(db: Session, username: str | None) -> int:
    """The id of the active user called ``username`` (looked up case-insensitively)."""
    if username is None:
        raise WorkflowAiUserError("not_set")
    user = UserRepository(db).get_by_username_ci(username)
    if user is None or not user.is_active:
        raise WorkflowAiUserError("not_active")
    return user.id
