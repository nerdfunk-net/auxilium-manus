"""Resolve a configured ``GitRepository`` for workflow steps."""

from __future__ import annotations

from typing import Any

from core.database import get_db_session
from services.git.repository_service import GitRepositoryService


def load_git_repository(repository_id: int) -> dict[str, Any]:
    """Resolve a ``git_repositories`` row into a ``GitService``-compatible dict.

    Raises ``ValueError`` if the repository is missing, inactive, or has no URL —
    callers surface this as a step failure.
    """
    db = get_db_session()
    try:
        repository = GitRepositoryService(db).get_repository(repository_id)
    finally:
        db.close()

    if repository is None:
        raise ValueError(f"Git repository {repository_id} not found")
    if not repository.get("is_active", True):
        raise ValueError(f"Git repository '{repository['name']}' is not active")
    if not str(repository.get("url") or "").strip():
        raise ValueError(f"Git repository '{repository['name']}' has no URL configured")

    return repository
