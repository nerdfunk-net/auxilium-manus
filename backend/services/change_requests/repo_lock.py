"""Per-repository advisory lock for change-request staging.

``open-change-request`` mutates a shared on-disk working tree (one clone dir per
git repository, not per run): ``checkout -B`` → write files → commit → push. Two
stage runs targeting the same repo would race on that tree and on ``index.lock``.
This lock serialises the git sequence across worker processes using Redis
``SET NX EX``.

Fail-soft by design: if Redis is unavailable the lock is skipped (a warning is
logged) rather than blocking a stage run — concurrent staging on one repo is
already discouraged operationally (see ``doc/CICD_PIPELINE.md``).
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


@contextmanager
def repo_stage_lock(git_repository_id: int) -> Iterator[None]:
    """Hold an advisory lock for ``git_repository_id`` for the duration of the
    ``with`` block. Blocks (up to ``_ACQUIRE_TIMEOUT_SECONDS``) while another
    holder has it; on timeout it proceeds anyway (fail-soft) after logging.
    """
    import service_factory

    cache = service_factory.build_cache_service()
    if cache is None:
        logger.warning(
            "repo_stage_lock: cache unavailable, proceeding without lock repo_id=%s",
            git_repository_id,
        )
        yield
        return

    key = f"cr-stage-lock:{git_repository_id}"
    acquired = False
    deadline = time.monotonic() + _ACQUIRE_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if cache.set_if_absent(key, {"held": True}, _LOCK_TTL_SECONDS):
            acquired = True
            break
        time.sleep(_POLL_INTERVAL_SECONDS)

    if not acquired:
        logger.warning(
            "repo_stage_lock: timed out waiting for lock, proceeding anyway repo_id=%s",
            git_repository_id,
        )

    try:
        yield
    finally:
        if acquired:
            cache.delete(key)
