"""Brackets around the shared on-disk git working tree (DN-C).

``GitService`` keeps one working tree per ``GitRepository`` row and many call sites share it.
Every use is a bracket: take the repository lease, open or clone the tree on the configured
branch, optionally pull (strictly: a failed pull is an error, C5-04) and hand the tree to the
caller; branch switches (change-request staging / deploy) are scoped and restore the configured
branch afterwards (C5-01).
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from git import Repo
from git.exc import GitCommandError

from models.failure import FailureInfo
from services.git.failure import GitOperationError
from services.git.repo_lock import git_repo_lock

logger = logging.getLogger(__name__)

SyncMode = Literal["strict", "best_effort", "never"]

_PULLED_KEY = "git-pulled:{}"


@dataclass(frozen=True)
class GitTree:
    path: Path
    head: str
    pulled: bool  # False when the pull was skipped (fresh) or failed with sync="best_effort"
    stale: bool


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except TypeError, ValueError:
        return None


def _cache() -> Any:
    import service_factory

    return service_factory.build_cache_service()


def _pulled_recently(repository: dict[str, Any]) -> bool:
    repo_id = _as_int(repository.get("id"))
    cache = _cache()
    if repo_id is None or cache is None:
        return False
    try:
        return bool(cache.exists(_PULLED_KEY.format(repo_id)))
    except Exception:  # noqa: BLE001 - freshness is an optimisation only
        return False


def _mark_pulled(repository: dict[str, Any], fresh_for_seconds: int) -> None:
    repo_id = _as_int(repository.get("id"))
    cache = _cache()
    if repo_id is None or cache is None:
        return
    with contextlib.suppress(Exception):
        cache.set(_PULLED_KEY.format(repo_id), {"pulled": True}, fresh_for_seconds)


def branch_of(repository: dict[str, Any]) -> str:
    return str(repository.get("branch") or "main")


@contextmanager
def git_work_tree(
    repository: dict[str, Any],
    *,
    sync: SyncMode = "strict",
    fresh_for_seconds: int = 15,
) -> Iterator[GitTree]:
    """Hold the repository lease while the caller reads the tree.

    ``strict`` raises when the pull fails (token expired, conflict, offline), ``best_effort``
    marks the tree stale and carries on, ``never`` does not pull. A pull that happened within
    ``fresh_for_seconds`` is not repeated, so a fan-out of children pulls once, not N times.
    """
    import service_factory

    git_service = service_factory.build_git_service()
    repo_id = _as_int(repository.get("id"))
    with git_repo_lock(repo_id if repo_id is not None else -1) as lease:
        repo = git_service.open_or_clone(repository)  # clones, or ensures the configured branch
        stale = pulled = False
        if sync != "never" and not _pulled_recently(repository):
            result = git_service.pull(repository, repo=repo)
            if result.success:
                pulled = True
                _mark_pulled(repository, fresh_for_seconds)
            elif sync == "strict":
                raise result.error()
            else:
                stale = True
        lease.ensure_held()
        head = repo.head.commit.hexsha if repo.head.is_valid() else ""
        yield GitTree(
            path=git_service.get_repo_path(repository), head=head, pulled=pulled, stale=stale
        )


@asynccontextmanager
async def async_scope(cm: Any) -> AsyncIterator[Any]:
    """Run a blocking context manager (lease acquisition polls with ``time.sleep``) so that
    entering and leaving happen in worker threads, never on the event loop."""
    import asyncio

    value = await asyncio.to_thread(cm.__enter__)
    try:
        yield value
    except BaseException as exc:
        suppress = await asyncio.to_thread(cm.__exit__, type(exc), exc, exc.__traceback__)
        if not suppress:
            raise
    else:
        await asyncio.to_thread(cm.__exit__, None, None, None)


def agit_work_tree(repository: dict[str, Any], **kwargs: Any) -> Any:
    """Async form of ``git_work_tree`` (``async with agit_work_tree(repo) as tree``)."""
    return async_scope(git_work_tree(repository, **kwargs))


@contextmanager
def git_branch_scope(
    git_service: Any,
    repo: Repo,
    repository: dict[str, Any],
    branch: str,
    base_ref: str | None = None,
) -> Iterator[None]:
    """Check out *branch* for the duration of the block, then the configured branch again."""
    git_service.checkout_new_branch(repo, branch, base_ref or f"origin/{branch}")
    try:
        yield
    except BaseException:
        # restore even when the block raised, but never mask the block's own error
        try:
            git_service.ensure_branch(repo, branch_of(repository))
        except GitCommandError, GitOperationError:
            logger.warning(
                "Could not restore branch %s after a failed block; the working tree may be on %s",
                branch_of(repository),
                branch,
                exc_info=True,
            )
        raise
    else:
        # A tree left on the change-request branch would be the next caller's problem: fail
        # this step instead of reporting success (C5-01).
        try:
            git_service.ensure_branch(repo, branch_of(repository))
        except GitOperationError:
            raise
        except GitCommandError as exc:
            raise GitOperationError(
                f"The configured branch {branch_of(repository)!r} could not be checked out again "
                f"after the change-request branch {branch!r}. Run the Git Clone step to reset "
                "the working tree.",
                failure=FailureInfo(phase="git", kind="repo_locked", hint="wait_for_other_run"),
            ) from exc
