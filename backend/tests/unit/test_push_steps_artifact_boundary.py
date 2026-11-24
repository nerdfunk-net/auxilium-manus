"""Device-push steps: an artifact-store error on one device (P-T write-first, W3a-01 / D1).

An error from the artifact store (disk, Redis, a missing artifact) in ``upload-config``,
``deploy-rendered-template`` or ``merge-config`` fails that device only, on ``run_per_device``
(the W3a-01 strict xfails of P-T became plain tests).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from models.workflow_context import ArtifactRef, DeviceStatus
from services.artifacts import InMemoryArtifactService
from services.network.netmiko.connection import CommandResult as NetmikoCommandResult
from services.network.netmiko.connection import DeployResult, FileTransferResult
from tests.unit._step_helpers import (
    call_step,
    make_context,
    patch_object_session,
    patch_ssh_credential,
)
from tests.unit.test_deploy_rendered_template_executor import (
    _base_config as _deploy_config,
)
from tests.unit.test_deploy_rendered_template_executor import (
    _device_with_rendered_template,
)
from tests.unit.test_merge_config_executor import _device as _merge_device
from tests.unit.test_upload_config_executor import _base_config, _device_with_running_config
from workflow_steps.deploy_rendered_template.executor import execute as deploy_rendered
from workflow_steps.merge_config.executor import execute as merge_config
from workflow_steps.upload_config.executor import execute as upload_config

_UPLOAD = "workflow_steps.upload_config.executor"
_DEPLOY = "workflow_steps.deploy_rendered_template.executor"
_MERGE = "workflow_steps.merge_config.executor"


def _device(device_id: str) -> Any:
    ref = ArtifactRef(artifact_id=f"artifact-{device_id}", kind="running_config", size_bytes=3)
    return _device_with_running_config(device_id).model_copy(
        update={"running_config_ref": ref, "name": device_id, "hostname": device_id}
    )


async def _run(*, resolve: Any) -> list[Any]:
    artifacts = InMemoryArtifactService()
    with (
        patch_ssh_credential(_UPLOAD),
        patch_object_session(_UPLOAD),
        patch(f"{_UPLOAD}.NetmikoService") as netmiko_cls,
        patch.object(artifacts, "resolve", new=AsyncMock(side_effect=resolve)),
    ):
        netmiko_cls.return_value.upload_file = AsyncMock(
            return_value=FileTransferResult(success=True, file_transferred=True, file_verified=True)
        )
        return await call_step(
            upload_config,
            _base_config(content_source="running_config"),
            make_context([_device("a"), _device("b")]),
            artifact_service=artifacts,
        )


def _resolve_failing_for(artifact_id: str, error: Exception) -> Any:
    async def resolve(ref: ArtifactRef) -> str:
        if ref.artifact_id == artifact_id:
            raise error
        return "hostname x\n"

    return resolve


@pytest.mark.asyncio
async def test_without_errors_both_devices_upload() -> None:
    outcomes = await _run(resolve=_resolve_failing_for("none", OSError()))

    assert [o.name for o in outcomes] == ["success"]
    assert set(outcomes[0].context.devices) == {"a", "b"}


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [OSError("disk gone"), RuntimeError("store down")])
async def test_an_artifact_error_fails_only_that_device(error: Exception) -> None:
    outcomes = await _run(resolve=_resolve_failing_for("artifact-a", error))

    by_name = {o.name: o.context.devices for o in outcomes}
    assert set(by_name["success"]) == {"b"}
    assert set(by_name["failure"]) == {"a"}
    assert by_name["failure"]["a"].status == DeviceStatus.FAILED


# --- deploy-rendered-template and merge-config (the open P-T items) -----------------------------


def _two_rendered_devices() -> Any:
    first = _device_with_rendered_template("a")
    second = _device_with_rendered_template("b")
    return make_context([first, second])


async def _store_ok(*args: Any, **kwargs: Any) -> ArtifactRef:
    return ArtifactRef(artifact_id="out", kind="command_output", size_bytes=1)


async def _run_deploy(*, resolve: Any = None, store: Any = _store_ok) -> list[Any]:
    artifacts = InMemoryArtifactService()
    with (
        patch_ssh_credential(_DEPLOY),
        patch_object_session(_DEPLOY),
        patch(f"{_DEPLOY}.NetmikoService") as netmiko_cls,
        patch.object(
            artifacts, "resolve", new=AsyncMock(side_effect=resolve, return_value="hostname x\n")
        ),
        patch.object(artifacts, "store", new=AsyncMock(side_effect=store)),
    ):
        netmiko_cls.return_value.deploy_config = AsyncMock(
            return_value=DeployResult(success=True, config_output="ok")
        )
        return await call_step(
            deploy_rendered,
            _deploy_config(),
            _two_rendered_devices(),
            artifact_service=artifacts,
        )


def _fail_once(error: Exception, ok: Any) -> Any:
    calls = {"n": 0}

    async def side_effect(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise error
        return ok

    return side_effect


@pytest.mark.asyncio
async def test_deploy_without_errors_both_devices_succeed() -> None:
    outcomes = await _run_deploy()

    assert [o.name for o in outcomes] == ["success"]
    assert set(outcomes[0].context.devices) == {"a", "b"}


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [OSError("disk gone"), RuntimeError("store down")])
async def test_deploy_resolve_error_fails_only_that_device(error: Exception) -> None:
    outcomes = await _run_deploy(resolve=_fail_once(error, "hostname x\n"))

    by_name = {o.name: o.context.devices for o in outcomes}
    assert len(by_name["success"]) == 1
    assert len(by_name["failure"]) == 1
    assert next(iter(by_name["failure"].values())).status == DeviceStatus.FAILED


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [OSError("disk gone"), RuntimeError("store down")])
async def test_deploy_store_error_fails_only_that_device(error: Exception) -> None:
    outcomes = await _run_deploy(store=_fail_once(error, await _store_ok()))

    by_name = {o.name: o.context.devices for o in outcomes}
    assert len(by_name["success"]) == 1
    assert len(by_name["failure"]) == 1


async def _run_merge(*, store: Any) -> list[Any]:
    artifacts = InMemoryArtifactService()
    result = NetmikoCommandResult(success=True, output="[OK]", command_outputs={})
    with (
        patch_ssh_credential(_MERGE),
        patch_object_session(_MERGE),
        patch(f"{_MERGE}.NetmikoService") as netmiko_cls,
        patch.object(artifacts, "store", new=AsyncMock(side_effect=store)),
    ):
        netmiko_cls.return_value.merge_config = AsyncMock(return_value=result)
        return await call_step(
            merge_config,
            {"credential_reference": "lab-ssh", "source_filename": "flash:partial.cfg"},
            make_context([_merge_device("a"), _merge_device("b")]),
            artifact_service=artifacts,
        )


@pytest.mark.asyncio
async def test_merge_without_errors_both_devices_succeed() -> None:
    outcomes = await _run_merge(store=_store_ok)

    assert [o.name for o in outcomes] == ["success"]
    assert set(outcomes[0].context.devices) == {"a", "b"}


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [OSError("disk gone"), RuntimeError("store down")])
async def test_merge_store_error_fails_only_that_device(error: Exception) -> None:
    outcomes = await _run_merge(store=_fail_once(error, await _store_ok()))

    by_name = {o.name: o.context.devices for o in outcomes}
    assert len(by_name["success"]) == 1
    assert len(by_name["failure"]) == 1


# --- connection errors, kept records and the temp file ----------------------------------------

_SECRET = "hunter2-must-not-be-stored"


async def _run_upload_netmiko_error(error: Exception, seen_paths: list[str]) -> list[Any]:
    artifacts = InMemoryArtifactService()

    async def upload_file(**kwargs: Any) -> Any:
        seen_paths.append(kwargs["local_path"])
        if len(seen_paths) == 1:
            raise error
        return FileTransferResult(success=True, file_transferred=True, file_verified=True)

    with (
        patch_ssh_credential(_UPLOAD),
        patch_object_session(_UPLOAD),
        patch(f"{_UPLOAD}.NetmikoService") as netmiko_cls,
        patch.object(artifacts, "resolve", new=AsyncMock(return_value="hostname x\n")),
    ):
        netmiko_cls.return_value.upload_file = upload_file
        return await call_step(
            upload_config,
            _base_config(content_source="running_config"),
            make_context([_device("a"), _device("b")]),
            artifact_service=artifacts,
        )


@pytest.mark.asyncio
async def test_upload_connection_error_fails_that_device_hides_its_text_and_removes_the_file() -> (
    None
):
    import os

    seen: list[str] = []

    outcomes = await _run_upload_netmiko_error(RuntimeError(f"ssh said pw={_SECRET}"), seen)

    by_name = {o.name: o.context.devices for o in outcomes}
    assert set(by_name["success"]) == {"b"} and set(by_name["failure"]) == {"a"}
    error = by_name["failure"]["a"].errors[-1]
    assert error.message == "RuntimeError" and _SECRET not in repr(by_name["failure"]["a"].errors)
    assert error.failure is not None
    assert seen and all(not os.path.exists(path) for path in seen)  # temp files are gone


@pytest.mark.asyncio
async def test_a_failed_upload_keeps_its_transfer_record() -> None:
    artifacts = InMemoryArtifactService()
    with (
        patch_ssh_credential(_UPLOAD),
        patch_object_session(_UPLOAD),
        patch(f"{_UPLOAD}.NetmikoService") as netmiko_cls,
        patch.object(artifacts, "resolve", new=AsyncMock(return_value="hostname x\n")),
    ):
        netmiko_cls.return_value.upload_file = AsyncMock(
            return_value=FileTransferResult(success=False, error="SCP disabled")
        )
        outcomes = await call_step(
            upload_config,
            _base_config(content_source="running_config"),
            make_context([_device("a")]),
            artifact_service=artifacts,
        )

    failed = {o.name: o.context.devices for o in outcomes}["failure"]["a"]
    assert failed.errors[-1].code == "upload_failed"
    assert failed.command_results  # the record rides on the failed device


@pytest.mark.asyncio
async def test_deploy_connection_error_hides_its_text_and_a_failed_deploy_keeps_its_record() -> (
    None
):
    artifacts = InMemoryArtifactService()
    calls = {"n": 0}

    async def deploy_config(**kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError(f"ssh said pw={_SECRET}")
        return DeployResult(success=False, config_output="partial", error="CLI error")

    with (
        patch_ssh_credential(_DEPLOY),
        patch_object_session(_DEPLOY),
        patch(f"{_DEPLOY}.NetmikoService") as netmiko_cls,
        patch.object(artifacts, "resolve", new=AsyncMock(return_value="hostname x\n")),
    ):
        netmiko_cls.return_value.deploy_config = deploy_config
        outcomes = await call_step(
            deploy_rendered, _deploy_config(), _two_rendered_devices(), artifact_service=artifacts
        )

    failed = {o.name: o.context.devices for o in outcomes}["failure"]
    assert len(failed) == 2
    first, second = failed["a"], failed["b"]
    assert first.errors[-1].message == "RuntimeError"
    assert _SECRET not in repr(first.errors)
    assert second.errors[-1].code == "deploy_failed" and second.command_results


@pytest.mark.asyncio
async def test_merge_connection_error_hides_its_text() -> None:
    artifacts = InMemoryArtifactService()
    calls = {"n": 0}

    async def merge(**kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError(f"ssh said pw={_SECRET}")
        return NetmikoCommandResult(success=True, output="[OK]", command_outputs={})

    with (
        patch_ssh_credential(_MERGE),
        patch_object_session(_MERGE),
        patch(f"{_MERGE}.NetmikoService") as netmiko_cls,
    ):
        netmiko_cls.return_value.merge_config = merge
        outcomes = await call_step(
            merge_config,
            {"credential_reference": "lab-ssh", "source_filename": "flash:partial.cfg"},
            make_context([_merge_device("a"), _merge_device("b")]),
            artifact_service=artifacts,
        )

    by_name = {o.name: o.context.devices for o in outcomes}
    assert len(by_name["success"]) == 1 and len(by_name["failure"]) == 1
    stored = repr(next(iter(by_name["failure"].values())).errors)
    assert _SECRET not in stored and "RuntimeError" in stored


@pytest.mark.asyncio
async def test_deploy_and_merge_outcome_summaries(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO", logger="workflow_steps.common.device_runner"):
        deploy = await _run_deploy()
        merge = await _run_merge(store=_store_ok)

    assert deploy[0].summary == "deployed rendered template to 2 device(s)"
    assert merge[0].summary == "merged flash:partial.cfg into running-config on 2 device(s)"
    lines = [r.getMessage() for r in caplog.records]
    for step in ("deploy-rendered-template", "merge-config"):
        assert any(line.startswith(f"{step} device 1/2") and "connecting" in line for line in lines)
        assert any(line.startswith(f"{step} device 2/2") and ": ok " in line for line in lines)


@pytest.mark.asyncio
async def test_failed_devices_have_a_failure_summary() -> None:
    outcomes = await _run_merge(store=_fail_once(OSError("disk gone"), await _store_ok()))

    failure = next(o for o in outcomes if o.name == "failure")
    assert failure.summary == "1 device(s) failed"


@pytest.mark.asyncio
async def test_upload_config_logs_a_line_per_device(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO", logger="workflow_steps.common.device_runner"):
        await _run(resolve=_resolve_failing_for("none", OSError()))

    lines = [r.getMessage() for r in caplog.records]
    assert any(line.startswith("upload-config device 1/2") and ": ok " in line for line in lines)
