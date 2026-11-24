"""store-artifact on a real ``GitArtifactSink``: the repository lease and the working tree (P-H).

W9-01 (cancelling the run while it waits for the lock leaked the lease), W9-02 (a failed
finalize left written files in the tree) and the lease re-check before the commit. The lock is a
fake; the sink and the working tree are real (``test_git_sink_session.py`` has the sink alone).
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.artifacts import InMemoryArtifactService
from services.git.failure import GitOperationError
from tests.unit._step_helpers import call_step, make_context, make_run
from tests.unit.test_git_sink_session import _SINK, Env
from tests.unit.test_store_artifact_executor import (
    _device_with_running_config,
    _mock_export_directory,
)
from workflow_steps.store_artifact.executor import _finalize_git_sink, execute

_CONFIG = {
    "destination": "git",
    "git_repository_id": 7,
    "content_source": "running_config",
    "filename_template": "{device.name}.cfg",
}


async def _run(env: Env, config: dict[str, Any] | None = None) -> list[Any]:
    artifacts = InMemoryArtifactService()
    with (
        env.patched(),
        patch("workflow_steps.store_artifact.executor._build_sink", return_value=env.sink),
        patch.object(artifacts, "resolve", new=AsyncMock(return_value="hostname lab\n")),
        _mock_export_directory(Path("/unused")),
    ):
        return await call_step(
            execute,
            {**_CONFIG, **(config or {})},
            make_context([_device_with_running_config()]),
            run=make_run(),
            artifact_service=artifacts,
        )


@pytest.mark.asyncio
async def test_a_committed_export_holds_the_lock_from_prepare_to_release(tmp_path: Path) -> None:
    env = Env(tmp_path)

    outcomes = await _run(env)

    assert [o.name for o in outcomes] == ["success"]
    assert env.events == ["acquire:7", "prepare", "commit", "release"]
    assert env.content("lab.cfg") == "hostname lab\n"


@pytest.mark.asyncio
async def test_a_failed_commit_fails_the_devices_and_leaves_a_clean_tree(tmp_path: Path) -> None:
    env = Env(tmp_path)
    env.git_service.commit.side_effect = None
    env.git_service.commit.return_value = MagicMock(
        success=False, error=lambda: GitOperationError("push rejected")
    )

    outcomes = await _run(env)

    failed = next(o for o in outcomes if o.name == "failure").context.devices["device-1"]
    assert "push rejected" in failed.errors[-1].message
    assert env.content("lab.cfg") is None  # the written file was put back
    assert env.events[-1] == "release"


@pytest.mark.asyncio
async def test_a_lost_lease_fails_the_devices_without_committing(tmp_path: Path) -> None:
    env = Env(tmp_path)
    env.lease.ensure_held.side_effect = GitOperationError("lock expired")

    outcomes = await _run(env)

    assert "failure" in [o.name for o in outcomes]
    env.git_service.commit.assert_not_called()
    assert env.content("lab.cfg") is None
    assert env.events[-1] == "release"


@pytest.mark.asyncio
async def test_a_cancelled_wait_for_the_lock_does_not_leak_the_lease(tmp_path: Path) -> None:
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
        patch("workflow_steps.store_artifact.executor._build_sink", return_value=env.sink),
        _mock_export_directory(Path("/unused")),
    ):
        task = asyncio.create_task(
            call_step(
                execute,
                dict(_CONFIG),
                make_context([_device_with_running_config()]),
                run=make_run(),
            )
        )
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


@pytest.mark.asyncio
async def test_when_every_device_failed_the_files_written_so_far_are_put_back() -> None:
    sink = MagicMock()
    sink.has_writes = True
    sink.discard_written = AsyncMock(return_value=1)
    sink.finalize = AsyncMock()

    await _finalize_git_sink(
        git_sink=sink,
        config={},
        context=make_context(),
        node_id="n",
        run_id=1,
        metadata={},
        success_devices={},
        failed_devices={"d1": _device_with_running_config()},
    )

    sink.discard_written.assert_awaited_once()
    sink.finalize.assert_not_called()
