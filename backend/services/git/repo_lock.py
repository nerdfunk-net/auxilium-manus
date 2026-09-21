"""Per-repository advisory lock for any git working-tree mutation.

``GitService``/``GitRepositoryService`` open one on-disk working tree per
``GitRepository`` row (``load_git_repository`` -> a single ``path``), shared by
every caller: ``open-change-request`` staging, the git-clone/git-pull/git-push
workflow steps, and ``store-artifact`` (destination: git). Two concurrent
callers against the *same* repo race on ``index.lock``, non-fast-forward
pushes, or partial commits -- whether they are two different runs, fan-out
children (cross-process, possibly different Hatchet workers), or two
independent sibling branches within one run (same process, concurrent since
branch-level parallelism -- see doc/HOWTO_BUILD_WORKFLOWS.md "Independent
branches run concurrently"). This lock serialises the git sequence across
worker processes using Redis ``SET NX EX``, so it covers all three triggers
with one mechanism.

Fail-soft by design: if Redis is unavailable the lock is skipped (a warning is
logged) rather than blocking a caller.

Two ways to use it:

- ``git_repo_lock(git_repository_id)`` -- a context manager, for a single
  synchronous block of git work (``open-change-request``, the git-clone/pull/
  push steps via ``git_workflow_step.py``).
- ``acquire_git_repo_lock``/``release_git_repo_lock`` -- the split primitives,
  for a caller whose critical section spans multiple ``await`` points/method
  calls (``store-artifact``'s prepare -> write* -> finalize lifecycle).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

logger = logging.getLogger(__name__)

_LOCK_TTL_SECONDS = 120
_ACQUIRE_TIMEOUT_SECONDS = 90
_POLL_INTERVAL_SECONDS = 1.0


def _lock_key(git_repository_id: int) -> str:
    return f"git-repo-lock:{git_repository_id}"


def acquire_git_repo_lock(git_repository_id: int) -> bool:
    """Block (up to ``_ACQUIRE_TIMEOUT_SECONDS``) until the lock for
    ``git_repository_id`` is held by this caller.

    Returns True when actually acquired -- the caller must then call
    ``release_git_repo_lock`` (typically in a ``finally``) once its git work
    is done. Returns False when Redis was unavailable or acquisition timed
    out (fail-soft: proceed anyway, matching ``git_repo_lock``'s behaviour).
    """
    import service_factory

    cache = service_factory.build_cache_service()
    if cache is None:
        logger.warning(
            "git_repo_lock: cache unavailable, proceeding without lock repo_id=%s",
            git_repository_id,
        )
        return False

    key = _lock_key(git_repository_id)
    deadline = time.monotonic() + _ACQUIRE_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if cache.set_if_absent(key, {"held": True}, _LOCK_TTL_SECONDS):
            return True
        time.sleep(_POLL_INTERVAL_SECONDS)

    logger.warning(
        "git_repo_lock: timed out waiting for lock, proceeding anyway repo_id=%s",
        git_repository_id,
    )
    return False


def release_git_repo_lock(git_repository_id: int, acquired: bool) -> None:
    """Release a lock previously acquired via ``acquire_git_repo_lock``.

    A no-op when ``acquired`` is False (nothing was actually held), so a
    caller can call this unconditionally in a ``finally`` regardless of
    whether acquisition succeeded.
    """
    if not acquired:
        return

    import service_factory

    cache = service_factory.build_cache_service()
    if cache is not None:
        cache.delete(_lock_key(git_repository_id))


@contextmanager
def git_repo_lock(git_repository_id: int) -> Iterator[None]:
    """Hold the advisory lock for ``git_repository_id`` for the duration of
    the ``with`` block. See module docstring for when to use this vs. the
    split ``acquire_git_repo_lock``/``release_git_repo_lock`` primitives.
    """
    acquired = acquire_git_repo_lock(git_repository_id)
    try:
        yield
    finally:
        release_git_repo_lock(git_repository_id, acquired)
