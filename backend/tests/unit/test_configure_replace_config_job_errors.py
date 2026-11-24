"""configure-replace-config: what one device's error does to the others (W3a-01).

Every problem of one device (``PyATSAPIError``, ``PyATSValidationError`` from ``run_job``, an
artifact that cannot be stored) fails that device only and the others still run: the step runs
on ``run_per_device``. The text of an unexpected error is never stored.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.workflow_context import DeviceStatus
from services.pyats.common.exceptions import PyATSAPIError, PyATSValidationError
from tests.unit._step_helpers import call_step, make_context
from tests.unit.test_configure_replace_config_executor import (
    _BASE_CONFIG,
    _NODE_ID,
    _device_with_testbed,
)
from workflow_steps.configure_replace_config.executor import execute

_MOD = "workflow_steps.configure_replace_config.executor"


async def _run(error: Exception) -> list:  # noqa: ANN202
    device = _device_with_testbed()
    with (
        patch("workflow_steps.common.run_session.object_session", return_value=MagicMock()),
        patch("workflow_steps.common.pyats_batch.PyATSSourceConfigService") as config_service,
        patch(f"{_MOD}.service_factory") as service_factory,
    ):
        config_service.return_value.resolve_credentials.return_value = MagicMock()
        shim = MagicMock()
        shim.run_job = AsyncMock(side_effect=error)
        service_factory.get_pyats_app_service.return_value = shim
        return await call_step(execute, _BASE_CONFIG, make_context([device]), node_id=_NODE_ID)


@pytest.mark.asyncio
async def test_a_shim_api_error_fails_the_device() -> None:
    outcomes = await _run(PyATSAPIError("shim unreachable"))

    failure = next(o for o in outcomes if o.name == "failure")
    (failed,) = failure.context.devices.values()
    assert failed.status == DeviceStatus.FAILED


@pytest.mark.asyncio
async def test_a_shim_validation_error_fails_the_device_too() -> None:
    outcomes = await _run(PyATSValidationError("shim refused the request"))

    failure = next(o for o in outcomes if o.name == "failure")
    (failed,) = failure.context.devices.values()
    assert failed.status == DeviceStatus.FAILED
    assert failed.errors[-1].failure is not None  # a closed-vocabulary record, no shim text
    assert "refused" not in failed.errors[-1].message


def _two_devices() -> list:  # noqa: ANN202
    first = _device_with_testbed()
    second = _device_with_testbed().model_copy(update={"id": "device-2", "name": "router2"})
    return [first, second]


def _ok_response(device_id: str) -> dict:
    commands = {
        "configure replace bootflash:new_config.txt force time 2": {
            "raw": "ok",
            "parsed": None,
            "error": None,
        },
        "configure confirm": {"raw": "", "parsed": None, "error": None},
    }
    return {"results": {device_id: {"success": True, "error": None, "commands": commands}}}


async def _run_two(config: dict, run_job, artifact_service=None) -> list:  # noqa: ANN001, ANN202
    with (
        patch("workflow_steps.common.run_session.object_session", return_value=MagicMock()),
        patch("workflow_steps.common.pyats_batch.PyATSSourceConfigService") as config_service,
        patch(f"{_MOD}.service_factory") as service_factory,
    ):
        config_service.return_value.resolve_credentials.return_value = MagicMock()
        shim = MagicMock()
        shim.run_job = AsyncMock(side_effect=run_job)
        shim.limits = AsyncMock(side_effect=RuntimeError("no limits"))
        service_factory.get_pyats_app_service.return_value = shim
        return await call_step(
            execute,
            config,
            make_context(_two_devices()),
            node_id=_NODE_ID,
            artifact_service=artifact_service,
        )


@pytest.mark.asyncio
async def test_a_validation_error_on_one_device_does_not_stop_the_other() -> None:
    async def run_job(creds, *, devices, **_kwargs):  # noqa: ANN001, ANN003, ANN202
        name = devices[0]["name"]
        if name == "device-1":
            raise PyATSValidationError("refused")
        return _ok_response(name)

    outcomes = await _run_two(_BASE_CONFIG, run_job)

    by = {o.name: o.context.devices for o in outcomes}
    assert set(by["success"]) == {"device-2"} and set(by["failure"]) == {"device-1"}


@pytest.mark.asyncio
async def test_an_unexpected_error_text_is_not_stored() -> None:
    async def run_job(creds, *, devices, **_kwargs):  # noqa: ANN001, ANN003, ANN202
        raise RuntimeError("shim said password=hunter2")

    outcomes = await _run_two(_BASE_CONFIG, run_job)

    stored = repr([d.errors for o in outcomes for d in o.context.devices.values()])
    assert "hunter2" not in stored


class _FailingStore:
    """An artifact service whose ``store`` raises (disk full, S3 down, ...)."""

    async def store(self, **_kwargs):  # noqa: ANN003, ANN201
        raise OSError("/var/artifacts: no space left")


@pytest.mark.asyncio
async def test_an_artifact_that_cannot_be_stored_fails_that_device_only() -> None:
    diff = "!Contextual Config Diffs:\n+hostname other"

    async def run_job(creds, *, devices, commands, **_kwargs):  # noqa: ANN001, ANN003, ANN202
        name = devices[0]["name"]
        if commands[0].startswith("show archive config differences"):
            in_sync = "!Contextual Config Diffs:\n!No changes were found"
            raw = diff if name == "device-1" else in_sync
            return {
                "results": {
                    name: {
                        "success": True,
                        "error": None,
                        "commands": {commands[0]: {"raw": raw, "parsed": None, "error": None}},
                    }
                }
            }
        return _ok_response(name)

    config = {**_BASE_CONFIG, "skip_if_no_pending_changes": True}
    outcomes = await _run_two(config, run_job, artifact_service=_FailingStore())

    by = {o.name: o.context.devices for o in outcomes}
    # device-2 is already in sync: skipped, no artifact needed. device-1 has a pending diff
    # that cannot be stored: it fails alone, with the class name only.
    assert set(by["success"]) == {"device-2"} and set(by["failure"]) == {"device-1"}
    assert by["failure"]["device-1"].errors[-1].message == "OSError"
    assert "no space" not in repr(by["failure"]["device-1"].errors)
