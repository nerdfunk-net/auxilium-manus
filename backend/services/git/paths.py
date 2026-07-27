"""
Git Path Resolution Service.

This module handles path resolution for git repositories,
providing a single responsibility for determining where repositories
are stored on disk.
"""

from __future__ import annotations

from pathlib import Path

from core.config import PROJECT_ROOT

_GIT_DATA_ROOT = PROJECT_ROOT / "data" / "git"


def _sanitize_git_subpath(raw: str) -> str:
    """Normalize a repo subpath under data/git/; reject ``..`` and absolute paths."""
    normalized = raw.replace("\\", "/").strip()
    if not normalized:
        raise ValueError("repository path/name is empty after normalization")
    # Reject absolute paths before stripping (e.g. "/etc/passwd").
    if normalized.startswith("/") or Path(normalized).is_absolute():
        raise ValueError("repository path/name must be a relative path")
    if normalized.startswith("./"):
        normalized = normalized[2:]

    parts = [part for part in normalized.split("/") if part and part != "."]
    if not parts:
        raise ValueError("repository path/name is empty after normalization")
    if ".." in parts:
        raise ValueError("repository path/name must not contain parent directory segments")
    # Reject Windows drive / UNC-style absolute leftovers after strip.
    if any(":" in part for part in parts):
        raise ValueError("repository path/name must be a relative path")

    return "/".join(parts)


def repo_path(repository: dict) -> Path:
    """Compute the on-disk path for a repository under ``data/git/``.

    Rejects ``..`` segments and any resolved path that escapes the git data root.
    """
    raw = repository.get("path") or repository.get("name")
    if raw is None or not str(raw).strip():
        raise ValueError("repository path/name is required")

    sub_path = _sanitize_git_subpath(str(raw))
    root = _GIT_DATA_ROOT.resolve()
    candidate = (root / sub_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"repository path escapes data/git: {raw!r}") from exc
    return candidate
