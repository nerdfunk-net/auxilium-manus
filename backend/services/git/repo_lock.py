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

Without a usable cache (Redis unreachable, or not configured) the outcome depends on
``GIT_REPO_LOCK_REQUIRED``: where it is set (the default outside development) the caller fails
with a retryable ``repo_locked`` error and does not touch the working tree; in development the lock
is skipped with a warning. A lock that stays held by someone else past the acquire timeout
always fails the caller -- proceeding would corrupt the shared working tree.

The lock has an owner: every acquisition stores a random token, release is compare-and-delete
(a holder whose lease expired never removes the next holder's lock) and a daemon thread renews
the lease while it is held. A holder that lost its lease finds out at its next
``GitRepoLease.ensure_held()`` instead of silently working unprotected (C1-07).

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
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import uuid4

logger = logging.getLogger(__name__)

_LOCK_TTL_SECONDS = 120
_RENEW_EVERY_SECONDS = 40  # the TTL stays 120 s
_ACQUIRE_TIMEOUT_SECONDS = 90
_POLL_INTERVAL_SECONDS = 1.0


# The lease of the innermost ``git_repo_lock`` block running in this context. GitService checks it
# before it mutates the shared tree, so a holder whose lease expired fails on its next commit or
# push instead of working unprotected (C1-07).
_current_lease: ContextVar[GitRepoLease | None] = ContextVar("git_repo_lease", default=None)


def ensure_current_lease_held() -> None:
    """Raise ``repo_locked`` when the enclosing ``git_repo_lock`` lease was lost; a no-op outside
    any lock block and for a lease that holds nothing (fail-soft, no Redis)."""
    lease = _current_lease.get()
    if lease is not None:
        lease.ensure_held()


def _lock_required() -> bool:
    from core.config import settings

    return settings.git_repo_lock_required


def _lock_unavailable() -> Exception:
    from models.failure import FailureInfo
    from services.git.failure import GitOperationError

    return GitOperationError(
        "The lock on this git repository could not be taken because Redis is unavailable; "
        "the git operation was not started. Try again once Redis is back.",
        failure=FailureInfo(phase="git", kind="repo_locked", retryable=True, hint="retry_later"),
    )


def _lock_key(git_repository_id: int) -> str:
    return f"git-repo-lock:{git_repository_id}"


@dataclass
class GitRepoLease:
    git_repository_id: int
    value: dict[str, str] | None  # None: no cache, nothing held (fail-soft)
    lost: bool = False
    _stop: threading.Event = field(default_factory=threading.Event)

    def ensure_held(self) -> None:
        """Raise ``GitOperationError`` (``repo_locked``) when the lease expired in use."""
        if self.lost:
            from models.failure import FailureInfo
            from services.git.failure import GitOperationError

            raise GitOperationError(
                "The lock on this git repository expired while it was in use",
                failure=FailureInfo(phase="git", kind="repo_locked", hint="wait_for_other_run"),
            )

    def release(self) -> None:
        self._stop.set()
        if self.value is None:
            return
        import service_factory

        cache = service_factory.build_cache_service()
        if cache is not None:
            # compare-and-delete: never deletes someone else's lock
            cache.delete_if_equals(_lock_key(self.git_repository_id), self.value)


def _renew(lease: GitRepoLease) -> None:
    import service_factory

    while not lease._stop.wait(_RENEW_EVERY_SECONDS):
        cache = service_factory.build_cache_service()
        if cache is None:
            return
        if not cache.expire_if_equals(
            _lock_key(lease.git_repository_id), lease.value, _LOCK_TTL_SECONDS
        ):
            lease.lost = True  # somebody else holds it now; the holder finds out at ensure_held()
            logger.error("git_repo_lock: lease lost repo_id=%s", lease.git_repository_id)
            return


def acquire_git_repo_lock(
    git_repository_id: int, *, timeout_seconds: float = _ACQUIRE_TIMEOUT_SECONDS
) -> GitRepoLease:
    """Block (up to ``timeout_seconds``) until the lock for ``git_repository_id`` is held by
    this caller and return its lease.

    The caller must call ``release_git_repo_lock(lease)`` (typically in a ``finally``) once its
    git work is done. When no cache is configured or Redis errors, the lease holds nothing
    (development) or ``GitOperationError`` is raised (``GIT_REPO_LOCK_REQUIRED``, the default
    outside development). Also raises ``GitOperationError``
    (``repo_locked``) when the lock is held by someone else for longer than the timeout --
    proceeding would corrupt the shared working tree (W4).
    """
    import service_factory

    cache = service_factory.build_cache_service()
    if cache is None:
        if _lock_required():
            logger.error("git_repo_lock: cache unavailable, refusing repo_id=%s", git_repository_id)
            raise _lock_unavailable()
        logger.warning(
            "git_repo_lock: cache unavailable, proceeding without lock repo_id=%s",
            git_repository_id,
        )
        return GitRepoLease(git_repository_id, None)

    key = _lock_key(git_repository_id)
    token = {"token": uuid4().hex}
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            if cache.set_if_absent(key, token, _LOCK_TTL_SECONDS, raise_on_error=True):
                lease = GitRepoLease(git_repository_id, token)
                threading.Thread(
                    target=_renew, args=(lease,), daemon=True, name=f"git-lock-{git_repository_id}"
                ).start()
                return lease
        except Exception as exc:
            # Redis died after the cache client was built: nothing is contended, so do not spin
            # for the whole timeout. Required: refuse. Otherwise skip the lock like "no cache".
            if _lock_required():
                logger.error(
                    "git_repo_lock: cache error, refusing repo_id=%s",
                    git_repository_id,
                    exc_info=True,
                )
                raise _lock_unavailable() from exc
            logger.warning(
                "git_repo_lock: cache error, proceeding without lock repo_id=%s",
                git_repository_id,
                exc_info=True,
            )
            return GitRepoLease(git_repository_id, None)
        time.sleep(_POLL_INTERVAL_SECONDS)

    logger.error("git_repo_lock: timed out waiting for lock repo_id=%s", git_repository_id)
    from models.failure import FailureInfo
    from services.git.failure import GitOperationError

    raise GitOperationError(
        f"Timed out after {int(timeout_seconds)}s waiting for the lock on git repository "
        f"{git_repository_id}; another run is still using it",
        failure=FailureInfo(
            phase="git",
            kind="repo_locked",
            retryable=True,
            elapsed_ms=int(timeout_seconds * 1000),
            hint="wait_for_other_run",
        ),
    )


def release_git_repo_lock(lease: GitRepoLease) -> None:
    """Release a lease acquired via ``acquire_git_repo_lock`` (a lease that holds nothing is a
    no-op, so a caller can call this unconditionally in a ``finally``)."""
    lease.release()


@contextmanager
def git_repo_lock(
    git_repository_id: int, *, timeout_seconds: float = _ACQUIRE_TIMEOUT_SECONDS
) -> Iterator[GitRepoLease]:
    """Hold the advisory lock for ``git_repository_id`` for the duration of
    the ``with`` block. See module docstring for when to use this vs. the
    split ``acquire_git_repo_lock``/``release_git_repo_lock`` primitives.
    """
    lease = acquire_git_repo_lock(git_repository_id, timeout_seconds=timeout_seconds)
    token = _current_lease.set(lease)
    try:
        yield lease
    finally:
        try:
            _current_lease.reset(token)
        except ValueError:
            # exited in another context (async_scope enters/leaves in worker threads); that
            # context copy is discarded with the thread call
            logger.debug("git_repo_lock: lease context already gone", exc_info=True)
        lease.release()
