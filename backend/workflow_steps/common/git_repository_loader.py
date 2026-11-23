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


def parse_repository_id(raw: Any, *, step_id: str) -> int | None:
    """A whole number (or its decimal text), or ``None`` when empty.

    ``True`` and ``7.9`` are refused: ``int()`` would turn them into repositories 1 and 7.
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool) or (isinstance(raw, float) and not raw.is_integer()):
        raise ValueError(f"{step_id}: git_repository_id must be a whole number")
    try:
        return int(raw)
    except TypeError, ValueError:
        raise ValueError(f"{step_id}: git_repository_id must be a whole number") from None


def require_repository_id(raw: Any, *, step_id: str, context: str = "") -> int:
    """Like :func:`parse_repository_id`, but an empty value is a configuration error.

    ``context`` completes the message ("... is required when source=git").
    """
    value = parse_repository_id(raw, step_id=step_id)
    if value is None:
        raise ValueError(f"{step_id}: git_repository_id is {context or 'not configured'}")
    return value
