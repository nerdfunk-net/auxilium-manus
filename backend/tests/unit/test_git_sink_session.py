"""``GitArtifactSink.session()``: the one owner of the repository lease (P-H, D5).

W9-01 (cancel-safe acquire), W9-02 (put the tree back on any failure) and W8-03 (re-check the
lease before the commit) used to be the callers' job, in two private copies that each lacked a
different one. Here the real sink runs against a real working tree; only the git service and
the lock are fakes.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import git
import pytest

from services.artifacts.sinks.git_sink import GitArtifactSink, GitSinkPrepareError
from services.git.failure import GitOperationError

_SINK = "services.artifacts.sinks.git_sink"


class Env:
    """A tracked file ``aci/kept.json`` in a real repository, a fake lock, a fake git service."""

    def __init__(self, root: Path, *, repository_id: int | None = 7) -> None:
        repo = git.Repo.init(root)
        with repo.config_writer() as cfg:
            cfg.set_value("user", "name", "t")
            cfg.set_value("user", "email", "t@example.com")
        (root / "aci").mkdir()
        (root / "aci" / "kept.json").write_text("old\n")
        repo.git.add("-A")
        repo.git.commit("-m", "init")
        self.root = root
        self.events: list[str] = []
        self.lease = MagicMock(name="lease")
        self.git_service = MagicMock()
        self.git_service.open_or_clone.side_effect = lambda *_a, **_k: (
            self.events.append("prepare") or repo
        )
        self.git_service.pull.return_value = SimpleNamespace(success=True)
        self.git_service.commit.side_effect = lambda *_a, **_k: (
            self.events.append("commit")
            or SimpleNamespace(success=True, commit_sha="c1", files_changed=1, message="ok")
        )
        with patch("service_factory.build_git_service", return_value=self.git_service):
            self.sink = GitArtifactSink(
                {"id": repository_id, "name": "r"} if repository_id is not None else {"name": "r"},
                repository_subdirectory="aci",
                pull_before_write=True,
                commit_after_write=True,
            )

    @contextmanager
    def lock(self, repository_id: int) -> Iterator[MagicMock]:
        self.events.append(f"acquire:{repository_id}")
        try:
            yield self.lease
        finally:
            self.events.append("release")

    def patched(self) -> Any:
        stack = patch(f"{_SINK}.git_repo_lock", self.lock)
        root = patch(f"{_SINK}.get_repo_path", return_value=self.root)
        outer = self

        class _Both:
            def __enter__(self) -> Env:
                stack.__enter__()
                root.__enter__()
                return outer

            def __exit__(self, *exc: object) -> None:
                root.__exit__(*exc)
                stack.__exit__(*exc)

        return _Both()

    async def write(self, name: str, content: str) -> None:
        await self.sink.write_text(relative_path=name, content=content, workflow_id="w", run_id="r")

    def content(self, name: str) -> str | None:
        path = self.root / "aci" / name
        return path.read_text() if path.exists() else None


@pytest.mark.asyncio
async def test_the_lock_is_held_from_prepare_to_finalize_and_then_released(tmp_path: Path) -> None:
    env = Env(tmp_path)
    with env.patched():
        async with env.sink.session():
            env.events.append("body")
            await env.write("fresh.json", "{}\n")
            result = await env.sink.finalize("msg")

    assert result is not None and result.committed
    assert env.events == ["acquire:7", "prepare", "body", "commit", "release"]
    env.lease.ensure_held.assert_called_once()


@pytest.mark.asyncio
async def test_an_error_in_the_body_puts_the_tree_back_and_releases_the_lock(
    tmp_path: Path,
) -> None:
    env = Env(tmp_path)
    with env.patched(), pytest.raises(RuntimeError, match="boom"):
        async with env.sink.session():
            await env.write("kept.json", "new\n")
            await env.write("fresh.json", "{}\n")
            raise RuntimeError("boom")

    assert env.content("kept.json") == "old\n"
    assert env.content("fresh.json") is None
    assert env.events[-1] == "release"


@pytest.mark.asyncio
async def test_a_failed_commit_leaves_a_clean_tree(tmp_path: Path) -> None:
    env = Env(tmp_path)
    env.git_service.commit.side_effect = None
    env.git_service.commit.return_value = SimpleNamespace(
        success=False, error=lambda: GitOperationError("push rejected")
    )
    with env.patched(), pytest.raises(GitOperationError, match="push rejected"):
        async with env.sink.session():
            await env.write("kept.json", "new\n")
            await env.sink.finalize("msg")

    assert env.content("kept.json") == "old\n"
    assert not env.sink.has_writes
    assert env.events[-1] == "release"


@pytest.mark.asyncio
async def test_a_lost_lease_neither_commits_nor_pushes_and_cleans_the_tree(tmp_path: Path) -> None:
    env = Env(tmp_path)
    env.lease.ensure_held.side_effect = GitOperationError("lock expired")
    with env.patched(), pytest.raises(GitOperationError, match="lock expired"):
        async with env.sink.session():
            await env.write("kept.json", "new\n")
            await env.sink.finalize("msg")

    env.git_service.commit.assert_not_called()
    env.git_service.push.assert_not_called()
    assert env.content("kept.json") == "old\n"
    assert env.events[-1] == "release"


@pytest.mark.asyncio
async def test_a_failing_prepare_is_a_prepare_error_and_still_releases_the_lock(
    tmp_path: Path,
) -> None:
    env = Env(tmp_path)
    env.git_service.open_or_clone.side_effect = RuntimeError("clone failed")
    with env.patched(), pytest.raises(GitSinkPrepareError, match="clone failed") as raised:
        async with env.sink.session():
            raise AssertionError("the body must not run")  # pragma: no cover

    assert isinstance(raised.value.__cause__, RuntimeError)
    assert env.events == ["acquire:7", "release"]


@pytest.mark.asyncio
async def test_a_repository_without_an_id_is_not_locked(tmp_path: Path) -> None:
    env = Env(tmp_path, repository_id=None)
    with env.patched():
        async with env.sink.session():
            env.events.append("body")

    assert env.events == ["prepare", "body"]


@pytest.mark.asyncio
async def test_a_cancelled_wait_for_the_lock_does_not_leak_the_lease(tmp_path: Path) -> None:
    """The real ``git_repo_lock`` and ``async_scope``; only the polling acquire is slow."""
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
    ):
        task = asyncio.create_task(_enter_and_exit(env.sink))
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
    env.git_service.open_or_clone.assert_not_called()


async def _enter_and_exit(sink: GitArtifactSink) -> None:
    async with sink.session():
        pass
