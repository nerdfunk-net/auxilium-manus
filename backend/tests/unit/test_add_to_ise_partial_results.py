"""add-to-ise: devices created before the ISE connection was lost keep their result (W6-01).

``get-ise-tacacs-key`` and ``update-ise-tacacs-key`` answer a lost connection with
``abort_outcomes`` (done devices stay ``success``, the rest fail with the transport cause).
``add-to-ise`` returns one ``failure`` outcome carrying the whole input context, so a device that
was already created in ISE looks failed and a retry hits "already exists".
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from services.ise.common.exceptions import ISEAPIError, ISEValidationError
from tests.unit._step_helpers import make_run
from tests.unit.test_add_to_ise_executor import (
    _BASE_CONFIG,
    _context,
    _device,
    _device_service,
    _patches,
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
            run=make_run(),
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


@pytest.mark.asyncio
async def test_a_device_created_before_the_loss_stays_a_success() -> None:
    outcomes = await _lose_the_connection_after_the_first_device()

    by_name = {o.name: o.context.devices for o in outcomes}
    assert set(by_name["success"]) == {"a"}
    assert set(by_name["failure"]) == {"b"}


@pytest.mark.asyncio
async def test_the_created_device_keeps_its_ise_bag_and_the_abort_is_recorded() -> None:
    outcomes = await _lose_the_connection_after_the_first_device()

    success = next(o for o in outcomes if o.name == "success")
    assert "ise" in success.context.devices["a"].attribute_bags
    assert success.context.metadata["node-1.aborted"] is True


@pytest.mark.asyncio
async def test_a_device_that_already_exists_keeps_its_exists_handle_on_abort() -> None:
    device_service = _device_service()
    created = device_service.create_device.return_value
    device_service.create_device = AsyncMock(
        side_effect=[
            ISEValidationError("device already exists", code="already_exists"),
            created,
            ISEAPIError("ISE ERS request failed with status 401"),
        ]
    )
    p1, p2, p3 = _patches(device_service)
    with p1, p2, p3:
        outcomes = await execute(
            config=_BASE_CONFIG,
            context=_context(
                {
                    "a": _device("a", name="router1"),
                    "b": _device("b", name="router2"),
                    "c": _device("c", name="router3"),
                }
            ),
            run=make_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )

    by_name = {o.name: set(o.context.devices) for o in outcomes}
    assert by_name == {"success": {"b"}, "exists": {"a"}, "failure": {"c"}}
