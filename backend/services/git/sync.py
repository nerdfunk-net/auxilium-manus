"""Ensure a configured GitRepository is cloned/up to date on local disk.

Thin wrapper around the shared ``GitService`` engine (clone/pull) for callers that
just need "give me the local working tree for this repository" — workflow steps that
read files out of a repo, rather than performing an explicit clone/pull step
themselves.

The pull runs under the repository lease (``services.git.tree_scope.git_work_tree``), which
stays held while the caller reads (``git_checkout`` / ``agit_checkout``). It is strict: a failed
pull raises instead of silently serving a stale tree (C5-04). Callers that can live with a
stale tree pass ``allow_stale=True``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any

from git import GitCommandError

from core.safe_urls import UnsafeURLError
from services.git.failure import annotate_failure
from services.git.tree_scope import async_scope, git_work_tree

logger = logging.getLogger(__name__)


def _record_stale_read(name: Any) -> None:
    """Make a stale read visible on the step (a warning run event) when a run is bound; outside
    a run (previews) only the log line is written (C5-04)."""
    from services.execution.run_events_reporter import current_run_event_context, emit_run_event

    context = current_run_event_context()
    if context is not None:
        emit_run_event(
            context,
            kind="git_stale",
            level="warning",
            message=f"Git repository '{name}' could not be refreshed; the last local copy was read",
        )


@contextmanager
def git_checkout(repository: dict[str, Any], *, allow_stale: bool = False) -> Iterator[Path]:
    """Hold the repository lease and yield the local root path of an up-to-date working tree.

    The lease is held for the whole ``with`` block, so a concurrent change-request checkout
    cannot switch the shared tree while the caller reads files (C2-06). Read inside the block,
    never keep the path after it. Raises when the pull fails unless ``allow_stale`` is set.
    """
    name = repository.get("name") or repository.get("id")
    if not str(repository.get("url") or "").strip():
        raise ValueError(f"Git repository '{name}' has no URL configured")

    with ExitStack() as stack:
        try:
            tree = stack.enter_context(
                git_work_tree(repository, sync="best_effort" if allow_stale else "strict")
            )
        except UnsafeURLError as exc:
            raise ValueError(
                f"Git repository '{name}' has an unsafe URL: {exc}"
            ) from annotate_failure(exc)
        except GitCommandError as exc:
            raise RuntimeError(f"Failed to clone git repository '{name}': {exc}") from exc
        if tree.stale:
            logger.warning("Pull failed for '%s' — using the stale local copy", name)
            _record_stale_read(name)
        # errors raised by the caller's own block pass through unchanged
        yield tree.path


def agit_checkout(repository: dict[str, Any], *, allow_stale: bool = False) -> Any:
    """Async form of ``git_checkout`` (``async with agit_checkout(repo) as root``); the blocking
    lease acquisition runs in a worker thread."""
    return async_scope(git_checkout(repository, allow_stale=allow_stale))


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
        raise ValueError(f"Git repository '{name}' has an unsafe URL: {exc}") from annotate_failure(
            exc
        )
    except GitCommandError as exc:
        raise RuntimeError(f"Failed to clone git repository '{name}': {exc}") from exc

    logger.info("Cloned git repository '%s'", name)
    return git_service.get_repo_path(repository)
