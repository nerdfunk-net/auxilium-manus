"""add-to-ise (W6-02): one device's unexpected error fails that device, not the step.

``"²".isdigit()`` is true but ``int("²")`` raises, and the field resolution sat outside every
``try``: one bad value raised the step after the devices before it were created in ISE.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from services.ise.common.exceptions import ISEValidationError
from tests.unit.test_add_to_ise_executor import (
    _BASE_CONFIG,
    _context,
    _device,
    _device_service,
    _patches,
    _run,
)
from workflow_steps.add_to_ise import executor as mod
from workflow_steps.add_to_ise.executor import execute

_SECRET = "s3cr3t-library-text 10.9.9.9"


def by_name_error(outcomes: list, device_id: str):
    failure = next(o for o in outcomes if o.name == "failure")
    return failure.context.devices[device_id].errors[-1]


async def _run_step(devices: dict, service: MagicMock, config: dict | None = None) -> list:
    p1, p2, p3 = _patches(service)
    with p1, p2, p3:
        return await execute(
            config={**_BASE_CONFIG, **(config or {})},
            context=_context(devices),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )


@pytest.mark.asyncio
async def test_a_non_ascii_digit_in_the_prefix_fails_that_device_after_the_first_was_created() -> (
    None
):
    service = _device_service()
    devices = {
        "a": _device("a", name="router1", attribute_bags={"c": {"ip": "10.0.0.1/24"}}),
        "b": _device("b", name="router2", attribute_bags={"c": {"ip": "10.0.0.2/²"}}),
    }

    outcomes = await _run_step(
        devices, service, {"ip_address": "{c.ip}", "use_address_prefix": True}
    )

    by_name = {o.name: set(o.context.devices) for o in outcomes}
    assert by_name["success"] == {"a"}
    assert by_name["failure"] == {"b"}
    assert service.create_device.await_count == 1
    assert by_name_error(outcomes, "b").code == "netmask_invalid"  # not the raw int() error


@pytest.mark.asyncio
async def test_an_unexpected_error_fails_that_device_and_hides_the_text() -> None:
    service = _device_service()
    created = service.create_device.return_value
    service.create_device = AsyncMock(side_effect=[created, OSError(_SECRET), created])
    devices = {
        "a": _device("a", name="router1"),
        "b": _device("b", name="router2"),
        "c": _device("c", name="router3"),
    }

    outcomes = await _run_step(devices, service)

    by_name = {o.name: o.context.devices for o in outcomes}
    assert set(by_name["success"]) == {"a", "c"}
    error = by_name["failure"]["b"].errors[-1]
    assert error.message == "OSError"
    assert error.failure is not None


@pytest.mark.asyncio
async def test_an_invalid_netmask_override_is_a_config_error_for_a_non_ascii_digit() -> None:
    with pytest.raises(ValueError, match="netmask_override"):
        mod._parse_netmask_override("²")


@pytest.mark.asyncio
async def test_a_field_error_fails_the_device_without_calling_ise() -> None:
    service = _device_service()
    devices = {"a": _device("a", name="router1", attribute_bags={"c": {"ip": "not-an-ip"}})}

    outcomes = await _run_step(devices, service, {"ip_address": "{c.ip}"})

    failed = next(o for o in outcomes if o.name == "failure").context.devices["a"]
    assert failed.errors[-1].code
    service.create_device.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_rejected_create_keeps_the_request_record_on_the_failed_device() -> None:
    service = _device_service()
    service.create_device = AsyncMock(side_effect=ISEValidationError("name is not allowed"))

    outcomes = await _run_step({"a": _device("a", name="router1")}, service)

    failed = next(o for o in outcomes if o.name == "failure").context.devices["a"]
    assert failed.errors[-1].code == "ise_device_create_rejected"
    assert failed.requests["node-1"][0].ok is False


@pytest.mark.asyncio
async def test_a_failed_device_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    service = _device_service()
    service.create_device = AsyncMock(side_effect=ISEValidationError("name is not allowed"))

    with caplog.at_level("WARNING"):
        await _run_step({"a": _device("a", name="router1")}, service)

    assert "device 'router1' failed (ise_device_create_rejected)" in caplog.text
