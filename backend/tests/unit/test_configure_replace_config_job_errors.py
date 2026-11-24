"""configure-replace-config: which errors from ``run_job`` stay inside the device (W3a-01).

``PyATSAPIError`` is caught and fails the device. ``PyATSValidationError`` from the same call
(a request the shim client refuses) is not, so it leaves the step and aborts every other device.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.workflow_context import DeviceStatus
from services.pyats.common.exceptions import PyATSAPIError, PyATSValidationError
from tests.unit._step_helpers import call_step, make_context, strict_xfail
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
        patch(f"{_MOD}.object_session", return_value=MagicMock()),
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


@strict_xfail("W3a-01", "only PyATSAPIError is caught around run_job")
@pytest.mark.asyncio
async def test_a_shim_validation_error_fails_the_device_too() -> None:
    outcomes = await _run(PyATSValidationError("shim refused the request"))

    failure = next(o for o in outcomes if o.name == "failure")
    (failed,) = failure.context.devices.values()
    assert failed.status == DeviceStatus.FAILED
