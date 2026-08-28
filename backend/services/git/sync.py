"""Ensure a configured GitRepository is cloned/up to date on local disk.

Thin wrapper around the shared ``GitService`` engine (clone/pull) for callers that
just need "give me the local working tree for this repository" — workflow steps that
read files out of a repo, rather than performing an explicit clone/pull step
themselves.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from git import GitCommandError

from core.safe_urls import UnsafeURLError

logger = logging.getLogger(__name__)


def clone_or_pull(repository: dict[str, Any]) -> Path:
    """Ensure the repository is available locally; return the root path.

    A pull failure on an already-cloned repo is logged and swallowed — the cached
    copy is used.
    """
    name = repository.get("name") or repository.get("id")
    if not str(repository.get("url") or "").strip():
        raise ValueError(f"Git repository '{name}' has no URL configured")

    import service_factory

    git_service = service_factory.build_git_service()
    repo_dir = git_service.get_repo_path(repository)
    repo_existed = (repo_dir / ".git").is_dir()

    try:
        repo = git_service.open_or_clone(repository)
    except UnsafeURLError as exc:
        raise ValueError(f"Git repository '{name}' has an unsafe URL: {exc}") from exc
    except GitCommandError as exc:
        raise RuntimeError(f"Failed to clone git repository '{name}': {exc}") from exc

    if repo_existed:
        pull_result = git_service.pull(repository, repo=repo)
        if pull_result.success:
            logger.info("Pulled git repository '%s' branch '%s'", name, repository.get("branch"))
        else:
            logger.warning(
                "Pull failed for '%s': %s — using cached copy", name, pull_result.message
            )
    else:
        logger.info("Cloned git repository '%s'", name)

    return repo_dir


def remove_and_clone(repository: dict[str, Any]) -> Path:
    """Remove any existing local copy and clone fresh; return the root path."""
    name = repository.get("name") or repository.get("id")
    if not str(repository.get("url") or "").strip():
        raise ValueError(f"Git repository '{name}' has no URL configured")

    import service_factory

    git_service = service_factory.build_git_service()
    try:
        git_service.clone(repository)
    except UnsafeURLError as exc:
        raise ValueError(f"Git repository '{name}' has an unsafe URL: {exc}") from exc
    except GitCommandError as exc:
        raise RuntimeError(f"Failed to clone git repository '{name}': {exc}") from exc

    logger.info("Cloned git repository '%s'", name)
    return git_service.get_repo_path(repository)
