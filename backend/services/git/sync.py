"""Ensure a configured GitRepository is cloned/up to date on local disk.

Thin wrapper around the shared ``GitService`` engine (clone/pull) for callers that
just need "give me the local working tree for this repository" — workflow steps that
read files out of a repo, rather than performing an explicit clone/pull step
themselves.

The pull runs under the repository lease (``services.git.tree_scope.git_work_tree``), which
stays held while the caller reads (``git_checkout`` / ``agit_checkout``). By default it is strict:
a failed pull raises instead of silently serving a stale tree (C5-04). Callers that can live with a
stale tree pass ``allow_stale=True``. A caller that passes ``refresh=False`` (``enrich-attributes``
unless ``refresh_repository`` is on) does NOT pull at all: it reads the local copy as it is, so the
tree may be behind ``origin``, ahead of it, or carry edits. That read is made visible as a run event
with the commit it read (no git command is run for it: nothing is checked per read) and is no
strict-pull guarantee.
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
from services.git.tree_scope import SyncMode, async_scope, git_work_tree

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


def _record_unrefreshed_read(name: Any, head: str) -> None:
    """A read that skipped the pull says which commit it read. It runs no git command."""
    from services.execution.run_events_reporter import current_run_event_context, emit_run_event

    short = head[:7] if head else "no commit"
    logger.info("Git repository '%s' read without a pull (commit %s)", name, short)
    context = current_run_event_context()
    if context is None:
        return
    emit_run_event(
        context,
        kind="git_not_refreshed",
        level="info",
        message=f"Git repository '{name}' was read as last pulled (commit {short}), not refreshed",
    )


@contextmanager
def git_checkout(
    repository: dict[str, Any], *, allow_stale: bool = False, refresh: bool = True
) -> Iterator[Path]:
    """Hold the repository lease and yield the local root path of an up-to-date working tree.

    The lease is held for the whole ``with`` block, so a concurrent change-request checkout
    cannot switch the shared tree while the caller reads files (C2-06). Read inside the block,
    never keep the path after it. Raises when the pull fails unless ``allow_stale`` is set.
    ``refresh=False`` skips the pull and reads the local copy as it is (a missing clone is still
    made); the lease is held all the same, so the read never sees a switched branch.
    """
    name = repository.get("name") or repository.get("id")
    if not str(repository.get("url") or "").strip():
        raise ValueError(f"Git repository '{name}' has no URL configured")

    sync: SyncMode = "never" if not refresh else ("best_effort" if allow_stale else "strict")
    with ExitStack() as stack:
        try:
            tree = stack.enter_context(git_work_tree(repository, sync=sync))
        except UnsafeURLError as exc:
            raise ValueError(
                f"Git repository '{name}' has an unsafe URL: {exc}"
            ) from annotate_failure(exc)
        except GitCommandError as exc:
            raise RuntimeError(f"Failed to clone git repository '{name}': {exc}") from exc
        if tree.stale:
            logger.warning("Pull failed for '%s' — using the stale local copy", name)
            _record_stale_read(name)
        if not refresh:
            _record_unrefreshed_read(name, tree.head)
        # errors raised by the caller's own block pass through unchanged
        yield tree.path


def agit_checkout(
    repository: dict[str, Any], *, allow_stale: bool = False, refresh: bool = True
) -> Any:
    """Async form of ``git_checkout`` (``async with agit_checkout(repo) as root``); the blocking
    lease acquisition runs in a worker thread."""
    return async_scope(git_checkout(repository, allow_stale=allow_stale, refresh=refresh))


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
