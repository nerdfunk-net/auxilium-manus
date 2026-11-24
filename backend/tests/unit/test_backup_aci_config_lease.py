"""backup-aci-config on a real ``GitArtifactSink``: the repository lease (P-H, W9-01 and W8-03).

The step holds the lock through ``GitArtifactSink.session()``, so a lost lease must stop the
commit, a cancelled wait for the lock must not leak the lease, and a failure puts the working
tree back. The lock is a fake; the sink and the working tree are real
(``test_git_sink_session.py`` has the sink on its own).
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from services.git.failure import GitOperationError
from tests.unit._step_helpers import call_step, make_context
from tests.unit.test_backup_aci_config_step import _Patched
from tests.unit.test_git_sink_session import _SINK, Env
from workflow_steps.backup_aci_config.executor import execute

_CONFIG = {"aci_source_id": "lab", "git_repository_id": 7}


@pytest.mark.asyncio
async def test_a_held_lease_commits_and_releases(tmp_path: Any) -> None:
    env = Env(tmp_path)
    with env.patched(), _Patched(sink=env.sink):
        outcomes = await call_step(execute, _CONFIG, make_context())

    assert "success" in [o.name for o in outcomes]
    assert env.events[0] == "acquire:7"
    assert "commit" in env.events
    assert env.events[-1] == "release"


@pytest.mark.asyncio
async def test_a_lost_lease_does_not_commit_and_cleans_the_tree(tmp_path: Any) -> None:
    env = Env(tmp_path)
    env.lease.ensure_held.side_effect = GitOperationError("lock expired")
    with env.patched(), _Patched(sink=env.sink), pytest.raises(GitOperationError):
        await call_step(execute, _CONFIG, make_context())

    env.git_service.commit.assert_not_called()
    assert not env.sink.has_writes
    assert not (tmp_path / "aci" / "access-policies.json").exists()
    assert env.events[-1] == "release"


@pytest.mark.asyncio
async def test_a_cancelled_wait_does_not_leak_the_lease(tmp_path: Any) -> None:
    env = Env(tmp_path)
    entered, proceed = threading.Event(), threading.Event()
    lease = MagicMock(name="lease")

    def slow_acquire(_repository_id: int, **_kwargs: Any) -> MagicMock:
        entered.set()
        proceed.wait(5)
        return lease

    with (
        patch("services.git.repo_lock.acquire_git_repo_lock", side_effect=slow_acquire),
        patch(f"{_SINK}.get_repo_path", return_value=tmp_path),
        _Patched(sink=env.sink),
    ):
        task = asyncio.create_task(call_step(execute, _CONFIG, make_context()))
        await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        proceed.set()  # the orphaned thread now gets the lock
        for _ in range(50):
            if lease.release.called:
                break
            await asyncio.sleep(0.05)

    lease.release.assert_called_once_with()
