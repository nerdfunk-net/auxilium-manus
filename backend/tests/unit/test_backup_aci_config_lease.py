"""backup-aci-config: the repository lease (P-T write-first, W9-01 and W8-03).

The step holds the repository lock from ``prepare`` to ``finalize`` but, unlike ``store-artifact``,
never calls ``lease.ensure_held()`` before the commit, and a cancelled wait for the lock leaves
the lease taken by the orphaned acquiring thread unreleased.
"""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import MagicMock, patch

import pytest

from services.git.service import GitOperationError
from tests.unit._step_helpers import call_step, make_context, strict_xfail
from tests.unit.test_backup_aci_config_step import EXEC, FakeSink, _Patched
from workflow_steps.backup_aci_config.executor import execute

_CONFIG = {"aci_source_id": "lab", "git_repository_id": 7}


@pytest.mark.asyncio
async def test_a_held_lease_commits_and_releases() -> None:
    with _Patched() as env:
        await call_step(execute, _CONFIG, make_context())

    assert env.sink.finalized_with is not None
    env.release.assert_called_once_with(env.lease)


@strict_xfail("W8-03", "no lease.ensure_held() before finalize: a lost lease still commits")
@pytest.mark.asyncio
async def test_a_lost_lease_does_not_commit_and_cleans_the_tree() -> None:
    sink = FakeSink()
    with _Patched(sink=sink) as env:
        env.lease.ensure_held.side_effect = GitOperationError("lock expired")
        with pytest.raises(GitOperationError):
            await call_step(execute, _CONFIG, make_context())

    assert sink.finalized_with is None
    assert sink.discarded == 1
    env.release.assert_called_once_with(env.lease)


@strict_xfail("W9-01", "the lease taken by the orphaned acquiring thread is never released")
@pytest.mark.asyncio
async def test_a_cancelled_wait_does_not_leak_the_lease() -> None:
    entered = threading.Event()
    proceed = threading.Event()
    lease = MagicMock(name="lease")

    def slow_acquire(_repository_id: int) -> MagicMock:
        entered.set()
        proceed.wait(5)
        return lease

    release = MagicMock()
    with _Patched() as env:
        env.acquire.side_effect = slow_acquire
        with patch(f"{EXEC}.release_git_repo_lock", release):
            task = asyncio.create_task(call_step(execute, _CONFIG, make_context()))
            await asyncio.to_thread(entered.wait, 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            proceed.set()  # the orphaned thread now gets the lock
            await asyncio.sleep(0.3)

    release.assert_called_once_with(lease)
