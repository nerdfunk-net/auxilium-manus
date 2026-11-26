"""backup-aci-config (Back Up ACI Config to Git): a git error ends on the ``failure`` handle (P-H).

The APIC part already ended on ``failure`` (``common/controller_failure.py``); a git error (pull,
lock, lease, commit, push) used to raise and stop the run. It now ends on ``failure`` with the git
``FailureInfo`` and the URL-scrubbed git message, the context unchanged, the working tree put back
and the lock released. Any other exception (a filesystem error, a bug) still raises; those cases
are pinned in ``test_backup_aci_config_step.py``.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from git.exc import GitCommandError

from models.failure import FailureInfo
from models.workflow_context import DeviceContext
from services.git.failure import GitOperationError, classify_git_exception
from tests.unit._step_helpers import call_step, make_context
from tests.unit.test_backup_aci_config_step import FakeSink, _Patched, _run
from tests.unit.test_git_sink_session import _SINK, Env
from workflow_steps.backup_aci_config.executor import execute

pytestmark = pytest.mark.asyncio

_CONFIG = {"aci_source_id": "lab", "git_repository_id": 7}
_PUSH_REJECTED = FailureInfo(phase="git", kind="push_rejected", hint="pull_first")
_SECRET_URL = "https://alice:s3cr3t@git.example.com/backups.git"


class _GitFailingSink(FakeSink):
    """A FakeSink whose prepare or finalize raises a given git error."""

    def __init__(
        self,
        *,
        prepare_error: BaseException | None = None,
        finalize_error: BaseException | None = None,
    ) -> None:
        super().__init__()
        self.prepare_error = prepare_error
        self.finalize_error = finalize_error

    async def prepare(self) -> None:
        if self.prepare_error is not None:
            raise self.prepare_error
        await super().prepare()

    async def finalize(self, message: str):
        if self.finalize_error is not None:
            raise self.finalize_error
        return await super().finalize(message)


async def test_a_failed_pull_ends_on_failure_with_the_scrubbed_message() -> None:
    error = GitOperationError(
        f"pull from {_SECRET_URL} failed: could not resolve host", failure=_PUSH_REJECTED
    )
    sink = _GitFailingSink(prepare_error=error)
    device = DeviceContext(id="d1", name="d1", hostname="d1")
    with _Patched(sink=sink):
        outcomes = await _run(devices=[device])

    assert [o.name for o in outcomes] == ["failure"]
    assert outcomes[0].failure == _PUSH_REJECTED
    summary = outcomes[0].summary or ""
    assert summary.startswith("git failed: pull from ")
    assert "s3cr3t" not in summary
    assert "could not resolve host" in summary
    assert list(outcomes[0].context.devices) == ["d1"]
    assert "n1.aci_backup" not in outcomes[0].context.metadata
    assert (sink.session_opened, sink.session_closed, sink.discarded) == (1, 1, 0)


async def test_a_rejected_push_ends_on_failure_and_puts_the_tree_back() -> None:
    sink = _GitFailingSink(
        finalize_error=GitOperationError("push rejected", failure=_PUSH_REJECTED)
    )
    with _Patched(sink=sink):
        outcomes = await _run()

    assert [o.name for o in outcomes] == ["failure"]
    assert outcomes[0].summary == "git failed: push rejected"
    assert outcomes[0].failure == _PUSH_REJECTED
    assert (sink.session_closed, sink.discarded) == (1, 1)


async def test_a_gitpython_error_is_classified() -> None:
    error = GitCommandError(["git", "push"], 128, stderr="fatal: Authentication failed")
    sink = _GitFailingSink(finalize_error=error)
    with _Patched(sink=sink):
        outcomes = await _run()

    assert [o.name for o in outcomes] == ["failure"]
    assert outcomes[0].failure == classify_git_exception(error)
    assert (outcomes[0].summary or "").startswith("git failed: Cmd('git') failed")


async def test_a_git_error_without_a_record_is_classified() -> None:
    error = GitOperationError("commit failed: nothing to see")
    sink = _GitFailingSink(finalize_error=error)
    with _Patched(sink=sink):
        outcomes = await _run()

    assert outcomes[0].failure == classify_git_exception(error)


async def test_a_long_git_message_is_cut() -> None:
    sink = _GitFailingSink(finalize_error=GitOperationError("x" * 5000, failure=_PUSH_REJECTED))
    with _Patched(sink=sink):
        outcomes = await _run()

    summary = outcomes[0].summary or ""
    assert len(summary) <= 500
    assert summary.endswith("…")


async def test_a_lock_timeout_ends_on_failure_with_the_retryable_record(tmp_path: Any) -> None:
    env = Env(tmp_path)
    locked = FailureInfo(phase="git", kind="repo_locked", retryable=True, hint="wait_for_other_run")

    @contextmanager
    def busy(repository_id: int) -> Generator[MagicMock]:
        raise GitOperationError(
            f"Timed out waiting for the lock on git repository {repository_id}", failure=locked
        )
        yield MagicMock()  # pragma: no cover

    with (
        patch(f"{_SINK}.git_repo_lock", busy),
        patch(f"{_SINK}.get_repo_path", return_value=tmp_path),
        _Patched(sink=env.sink),
    ):
        outcomes = await call_step(execute, _CONFIG, make_context())

    assert [o.name for o in outcomes] == ["failure"]
    assert outcomes[0].failure == locked
    env.git_service.commit.assert_not_called()


async def test_a_prepare_error_is_recorded_from_its_git_cause() -> None:
    # GitPython errors carry no record of their own: the record must come from the git error,
    # not from the GitSinkPrepareError wrapper around it.
    error = GitCommandError(["git", "pull"], 1, stderr="fatal: could not read from remote")
    sink = _GitFailingSink(prepare_error=error)
    with _Patched(sink=sink):
        outcomes = await _run()

    assert [o.name for o in outcomes] == ["failure"]
    assert outcomes[0].failure == classify_git_exception(error)
