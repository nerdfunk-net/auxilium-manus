"""
Git Path Resolution Service.

This module handles path resolution for git repositories,
providing a single responsibility for determining where repositories
are stored on disk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from core.config import PROJECT_ROOT


def repo_path(repository: Dict) -> Path:
    """Compute the on-disk path for a repository.

    Args:
        repository: Repository metadata dict with keys like 'name' and optional 'path'.

    Returns:
        Absolute Path to the repository working directory under data/git/.

    Example:
        >>> repo = {"name": "my-configs", "path": "configs"}
        >>> repo_path(repo)
        Path('/data/git/configs')
    """
    sub_path = (repository.get("path") or repository["name"]).lstrip("/")
    return PROJECT_ROOT / "data" / "git" / sub_path
