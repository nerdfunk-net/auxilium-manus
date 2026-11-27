"""W9 (P-C step 4): the per-device boundary of the file and artifact steps.

``store-artifact`` and ``read-from-file`` run on ``run_per_device``: an unexpected exception fails
that device only, its text never reaches the stored run (class name + ``FailureInfo``). A git
error the app built itself (``GitOperationError``) keeps its text and its ``FailureInfo`` so a
rejected push still reads as one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.failure import FailureInfo
from services.artifacts import InMemoryArtifactService
from services.git.failure import GitOperationError
from tests.unit._step_helpers import call_step, make_context, make_device
from tests.unit.test_store_artifact_executor import (
    _device_with_running_config,
    _mock_export_directory,
)
from workflow_steps.read_from_file import executor as read_from_file
from workflow_steps.store_artifact.executor import execute as store_execute

_SECRET = "s3cr3t-sink-text /srv/exports/10.9.9.9"
_STORE = "workflow_steps.store_artifact.executor"


def _failed(outcomes: list[Any], device_id: str):
    return next(o for o in outcomes if o.name == "failure").context.devices[device_id]


def _config_device(device_id: str):
    return _device_with_running_config().model_copy(update={"id": device_id, "name": device_id})


class _Sink:
    destination = "filesystem"

    def __init__(self, failing: set[str] | None = None, error: Exception | None = None) -> None:
        self.failing = failing or set()
        self.error = error or OSError(_SECRET)
        self.written: list[str] = []

    async def write_text(self, *, relative_path: str, content: str, **_: Any):
        if any(name in relative_path for name in self.failing):
            raise self.error
        self.written.append(relative_path)
        return MagicMock(
            path=relative_path, destination="filesystem", size_bytes=len(content), sha256="x"
        )


async def _store(devices, sink, config: dict | None = None):
    artifacts = InMemoryArtifactService()
    with (
        patch(f"{_STORE}._build_sink", return_value=(sink, None)),
        patch.object(artifacts, "resolve", new=AsyncMock(return_value="hostname x\n")),
        _mock_export_directory(Path("/unused")),
    ):
        return await call_step(
            store_execute,
            {
                "content_source": "running_config",
                "filename_template": "{device.name}.cfg",
                **(config or {}),
            },
            make_context(devices),
            artifact_service=artifacts,
        )


@pytest.mark.asyncio
async def test_store_artifact_hides_the_text_of_a_sink_error() -> None:
    outcomes = await _store([_config_device("a")], _Sink(failing={"a.cfg"}))

    error = _failed(outcomes, "a").errors[-1]
    assert error.message == "OSError"
    assert _SECRET not in error.message
    assert error.failure is not None
    assert error.failure.exception_type == "OSError"


@pytest.mark.asyncio
async def test_store_artifact_one_failing_device_keeps_the_others_and_their_records() -> None:
    outcomes = await _store(
        [_config_device("a"), _config_device("b"), _config_device("c")],
        _Sink(failing={"b.cfg"}),
    )

    by_name = {o.name: o for o in outcomes}
    assert list(by_name["success"].context.devices) == ["a", "c"]
    assert list(by_name["failure"].context.devices) == ["b"]
    records = by_name["success"].context.metadata["node-1.stored_artifacts"]
    assert [r["device_id"] for r in records] == ["a", "c"]  # context order, not completion order
    assert by_name["failure"].context.metadata == by_name["success"].context.metadata


@pytest.mark.asyncio
async def test_store_artifact_missing_content_carries_a_failure_record() -> None:
    device = make_device("a")
    outcomes = await _store([device], _Sink())

    error = _failed(outcomes, "a").errors[-1]
    assert error.code == "missing_content"
    assert error.failure is not None


class _GitSession:
    """What ``GitArtifactSink.session()`` yields for the step: prepare/finalize that can fail."""

    has_writes = True
    repository_ref = 7
    destination = "git"

    def __init__(self, *, prepare: Exception | None = None, finalize: Exception | None = None):
        self._prepare = prepare
        self._finalize = finalize
        self.written: list[str] = []

    def session(self):
        from contextlib import asynccontextmanager

        from services.artifacts.sinks.git_sink import GitSinkPrepareError

        @asynccontextmanager
        async def _cm():
            if self._prepare is not None:
                raise GitSinkPrepareError(str(self._prepare)) from self._prepare
            yield self

        return _cm()

    async def write_text(self, *, relative_path: str, content: str, **_: Any):
        self.written.append(relative_path)
        return MagicMock(path=relative_path, destination="git", size_bytes=1, sha256="x")

    async def finalize(self, message: str):
        if self._finalize is not None:
            raise self._finalize

    async def discard_written(self) -> None:
        return None


async def _store_git(sink):
    artifacts = InMemoryArtifactService()
    with (
        patch(f"{_STORE}._build_sink", return_value=(sink, sink)),
        patch.object(artifacts, "resolve", new=AsyncMock(return_value="hostname x\n")),
        _mock_export_directory(Path("/unused")),
    ):
        return await call_step(
            store_execute,
            {
                "destination": "git",
                "git_repository_id": 7,
                "content_source": "running_config",
                "filename_template": "{device.name}.cfg",
            },
            make_context([_config_device("a")]),
            artifact_service=artifacts,
        )


@pytest.mark.asyncio
async def test_a_rejected_push_keeps_its_text_and_its_failure_record() -> None:
    info = FailureInfo(phase="git", kind="push_rejected")
    outcomes = await _store_git(
        _GitSession(finalize=GitOperationError("push rejected: non-fast-forward", failure=info))
    )

    error = _failed(outcomes, "a").errors[-1]
    assert "push rejected" in error.message
    assert error.failure == info


@pytest.mark.asyncio
async def test_a_git_error_is_scrubbed_of_url_credentials() -> None:
    url = "https://bot:s3cr3t-token@git.example.com/r.git"
    outcomes = await _store_git(_GitSession(finalize=GitOperationError(f"push to {url} failed")))

    error = _failed(outcomes, "a").errors[-1]
    assert "s3cr3t-token" not in error.message
    assert "git.example.com" in error.message


@pytest.mark.asyncio
async def test_a_finalize_error_that_is_not_a_git_error_is_reduced_to_its_class() -> None:
    outcomes = await _store_git(_GitSession(finalize=KeyError(_SECRET)))

    error = _failed(outcomes, "a").errors[-1]
    assert error.message == "KeyError"
    assert error.failure is not None


@pytest.mark.asyncio
async def test_a_prepare_failure_is_a_whole_step_failure_with_its_record() -> None:
    info = FailureInfo(phase="git", kind="merge_conflict")
    outcomes = await _store_git(_GitSession(prepare=GitOperationError("pull failed", failure=info)))

    assert [o.name for o in outcomes] == ["success", "failure"]
    assert outcomes[0].context.devices == {}
    failure = outcomes[1]
    assert failure.failure == info
    assert failure.summary == "pull failed"
    assert failure.context.devices["a"].errors[-1].failure == info


# --- read-from-file ------------------------------------------------------------------------


async def _read(devices, merge):
    with (
        patch.object(read_from_file, "merge_into_device_attribute", merge),
        patch.object(read_from_file, "resolve_source_root", AsyncMock(return_value=Path("/x"))),
        patch.object(read_from_file, "resolve_within_repo") as within,
        patch.object(read_from_file, "parse_structured_document", return_value={"k": 1}),
    ):
        within.return_value.is_file.return_value = True
        within.return_value.read_text.return_value = "k: 1\n"
        return await call_step(
            read_from_file.execute,
            {"source": "filesystem", "path": "a.yaml", "destination_path": "custom.data"},
            make_context(devices),
        )


@pytest.mark.asyncio
async def test_read_from_file_hides_the_text_of_an_unexpected_merge_error() -> None:
    def merge(device, destination, document, *, overwrite):
        if device.id == "b":
            raise OSError(_SECRET)
        return device

    outcomes = await _read([make_device("a"), make_device("b")], merge)

    by_name = {o.name: o for o in outcomes}
    assert list(by_name["success"].context.devices) == ["a"]
    error = by_name["failure"].context.devices["b"].errors[-1]
    assert error.message == "OSError"
    assert error.failure is not None
    assert error.step_id == "read-from-file"


# --- git steps -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_git_step_without_a_repository_fails_every_device_with_a_git_code() -> None:
    from workflow_steps.git_clone.executor import execute as clone_execute

    outcomes = await call_step(clone_execute, {}, make_context([make_device("a")]))

    failure = next(o for o in outcomes if o.name == "failure")
    error = failure.context.devices["a"].errors[-1]
    assert error.code == "git_operation_failed"
    assert error.step_id == "git-clone"
    assert failure.failure is not None
    assert failure.summary == error.message
