"""store-artifact: cancelling the run while it waits for the repository lock (W9-01).

``acquire_git_repo_lock`` blocks (it polls Redis) and runs in a thread. If the awaiting task is
cancelled, the thread keeps going and takes the lease afterwards; nothing releases it, so every
later git step on that repository waits until the lease times out.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch

import pytest

from services.artifacts.sinks.git_sink import GitArtifactSink
from tests.unit._step_helpers import (
    call_step,
    make_context,
    make_device,
    make_run,
    strict_xfail,
)
from workflow_steps.store_artifact.executor import execute

_MOD = "workflow_steps.store_artifact.executor"


@pytest.mark.asyncio
@strict_xfail("W9-01", "the lease taken by the orphaned thread is never released")
async def test_a_cancelled_wait_does_not_leak_the_lease() -> None:
    entered = threading.Event()
    proceed = threading.Event()
    lease = MagicMock(name="lease")

    def slow_acquire(_repository_id: int) -> MagicMock:
        entered.set()
        proceed.wait(5)
        return lease

    sink = create_autospec(GitArtifactSink, instance=True)
    sink.destination = "git"
    sink.repository_id = 7
    sink.prepare = AsyncMock()
    sink.has_writes = False
    release = MagicMock()

    with (
        patch(f"{_MOD}._build_sink", return_value=sink),
        patch(f"{_MOD}.acquire_git_repo_lock", side_effect=slow_acquire),
        patch(f"{_MOD}.release_git_repo_lock", release),
        patch(f"{_MOD}.GeneralSettingsService") as settings,
        patch(f"{_MOD}.get_db_session", return_value=MagicMock()),
    ):
        settings.return_value.resolved_export_directory.return_value = Path("/unused")
        task = asyncio.create_task(
            call_step(
                execute,
                {"destination": "git", "git_repository_id": 7, "content_source": "running_config"},
                make_context([make_device("d1")]),
                run=make_run(),
            )
        )
        await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        proceed.set()  # the orphaned thread now gets the lock
        await asyncio.sleep(0.3)

    release.assert_called_once_with(lease)
