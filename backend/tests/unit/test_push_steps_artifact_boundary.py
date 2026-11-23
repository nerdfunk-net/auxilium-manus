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
from services.network.netmiko.connection import FileTransferResult
from tests.unit._step_helpers import (
    call_step,
    make_context,
    patch_object_session,
    patch_ssh_credential,
    strict_xfail,
)
from tests.unit.test_upload_config_executor import _base_config, _device_with_running_config
from workflow_steps.upload_config.executor import execute as upload_config

_UPLOAD = "workflow_steps.upload_config.executor"


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
