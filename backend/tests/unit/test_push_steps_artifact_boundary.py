"""Device-push steps: an artifact-store error on one device (P-T write-first, W3a-01 / D1).

``artifact_service.resolve`` runs before the Netmiko ``try`` in ``upload-config``; an error from
the store (disk, Redis, a missing artifact) is not a ``ServiceError``. It must fail that device
only; today it leaves the per-device boundary.
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
    strict_xfail,
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


@strict_xfail("W3a-01", "resolve() runs outside the per-device try: the step aborts")
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


@strict_xfail("W3a-01", "resolve() in _load_deploy_commands runs outside the per-device try")
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


@strict_xfail("W3a-01", "artifact store() in _merge_on_device runs outside the per-device try")
@pytest.mark.asyncio
@pytest.mark.parametrize("error", [OSError("disk gone"), RuntimeError("store down")])
async def test_merge_store_error_fails_only_that_device(error: Exception) -> None:
    outcomes = await _run_merge(store=_fail_once(error, await _store_ok()))

    by_name = {o.name: o.context.devices for o in outcomes}
    assert len(by_name["success"]) == 1
    assert len(by_name["failure"]) == 1
