"""add-to-ise: devices created before the ISE connection was lost keep their result (W6-01).

``get-ise-tacacs-key`` and ``update-ise-tacacs-key`` answer a lost connection with
``abort_outcomes`` (done devices stay ``success``, the rest fail with the transport cause).
``add-to-ise`` returns one ``failure`` outcome carrying the whole input context, so a device that
was already created in ISE looks failed and a retry hits "already exists".
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from services.ise.common.exceptions import ISEAPIError
from tests.unit._step_helpers import strict_xfail
from tests.unit.test_add_to_ise_executor import (
    _BASE_CONFIG,
    _context,
    _device,
    _device_service,
    _patches,
    _run,
)
from workflow_steps.add_to_ise.executor import execute


async def _lose_the_connection_after_the_first_device() -> list:  # noqa: ANN202
    device_service = _device_service()
    created = device_service.create_device.return_value
    device_service.create_device = AsyncMock(
        side_effect=[created, ISEAPIError("ISE ERS request failed with status 401")]
    )
    p1, p2, p3 = _patches(device_service)
    with p1, p2, p3:
        return await execute(
            config=_BASE_CONFIG,
            context=_context(
                {"a": _device("a", name="router1"), "b": _device("b", name="router2")}
            ),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )


@pytest.mark.asyncio
async def test_a_lost_connection_fails_the_devices_that_were_not_reached() -> None:
    outcomes = await _lose_the_connection_after_the_first_device()

    failure = next(o for o in outcomes if o.name == "failure")
    assert "b" in failure.context.devices
    assert failure.failure is not None


@strict_xfail("W6-01", "one failure outcome with the whole context: the created device is lost")
@pytest.mark.asyncio
async def test_a_device_created_before_the_loss_stays_a_success() -> None:
    outcomes = await _lose_the_connection_after_the_first_device()

    by_name = {o.name: o.context.devices for o in outcomes}
    assert set(by_name["success"]) == {"a"}
    assert set(by_name["failure"]) == {"b"}
