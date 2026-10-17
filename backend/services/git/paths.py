"""
Git Path Resolution Service.

This module handles path resolution for git repositories,
providing a single responsibility for determining where repositories
are stored on disk.
"""

from __future__ import annotations

import glob
import os
import re
import stat
from pathlib import Path

from core.config import PROJECT_ROOT
from core.domain_exceptions import AccessDeniedError

_GIT_DATA_ROOT = PROJECT_ROOT / "data" / "git"
_GIT_DIR_NAME = ".git"
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


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


def resolve_within_repo(repo_root: str | Path, relative: str | None) -> Path:
    """Resolve ``relative`` under ``repo_root`` and fail closed if it escapes.

    Uses proper path-boundary containment (``Path.is_relative_to``), not a string
    ``startswith`` — ``/data/git/foo-other`` must not count as inside
    ``/data/git/foo``. Symlinks are resolved (``Path.resolve``), matching the
    previous ``os.path.realpath`` behaviour. An absolute or ``..`` ``relative``
    that lands outside the repo raises ``AccessDeniedError``.
    """
    root = Path(repo_root).resolve()
    target = (root / relative).resolve() if relative else root
    if not target.is_relative_to(root):
        raise AccessDeniedError("Access denied: path is outside repository")
    if _GIT_DIR_NAME in target.relative_to(root).parts:
        raise AccessDeniedError("Access denied: path is inside .git")
    return target


def validate_relative_glob(value: str, *, field: str, allow_empty: bool = False) -> str:
    """Return ``value`` stripped, or raise ``ValueError`` if it could address a path outside
    a repository: NUL byte, absolute POSIX/Windows path, any ``..`` or ``.git`` segment."""
    text = (value or "").strip()
    if not text:
        if allow_empty:
            return ""
        raise ValueError(f"{field} is required")
    if "\x00" in text:
        raise ValueError(f"{field} contains a NUL byte")
    normalized = text.replace("\\", "/")
    if normalized.startswith("/") or _WINDOWS_DRIVE.match(normalized):
        raise ValueError(f"{field} must be relative to the repository root")
    parts = [p for p in normalized.split("/") if p not in ("", ".")]
    if ".." in parts:
        raise ValueError(f"{field} must not contain '..'")
    if _GIT_DIR_NAME in parts:
        raise ValueError(f"{field} must not address the .git directory")
    return text


def is_contained_regular_file(repo_root: str | Path, candidate: str | Path) -> bool:
    """True only for a non-symlink regular file whose real path stays inside ``repo_root``
    and outside ``.git``. Used for every file found by a glob or a directory walk."""
    root = Path(repo_root).resolve()
    path = Path(candidate)
    try:
        if path.is_symlink():
            return False
        resolved = path.resolve(strict=True)
        if not stat.S_ISREG(resolved.stat().st_mode) or not resolved.is_relative_to(root):
            return False
        return _GIT_DIR_NAME not in resolved.relative_to(root).parts
    except OSError:
        return False


def list_repo_files(repo_root: str | Path, directory: str, pattern: str) -> list[Path]:
    """Glob ``pattern`` below ``directory`` and keep only contained regular files.

    ``directory`` keeps the historical tolerance for a leading slash (treated as relative);
    ``pattern`` does not -- an absolute pattern is the S4-01 bug."""
    root = Path(repo_root).resolve()
    clean_dir = validate_relative_glob(
        (directory or "").lstrip("/\\"), field="directory", allow_empty=True
    )
    clean_pattern = validate_relative_glob(pattern, field="filename_pattern")
    search_root = root / clean_dir if clean_dir else root
    matches = glob.glob(str(search_root / "**" / clean_pattern), recursive=True)
    if not matches:
        matches = glob.glob(str(search_root / clean_pattern))
    return [Path(m).resolve() for m in sorted(matches) if is_contained_regular_file(root, m)]


def write_text_within_repo(repo_root: str | Path, relative: str, content: str) -> Path:
    """Write below ``repo_root`` without following a symlink at any component (S4-05)."""
    root = Path(repo_root).resolve()
    rel_parts = Path(relative).parts
    if Path(relative).is_absolute() or ".." in rel_parts or _GIT_DIR_NAME in rel_parts:
        raise AccessDeniedError("Access denied: path is outside repository")
    cursor = root
    for part in rel_parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise AccessDeniedError("Access denied: refusing to write through a symlink")
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.parent.resolve().is_relative_to(root):
        raise AccessDeniedError("Access denied: path is outside repository")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(target, flags, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)
    return target
