"""``connection_device_type``: the one place a step turns a device and the step's driver override
into a Netmiko device type (W3a-17)."""

from __future__ import annotations

from pathlib import Path

import pytest

from models.workflow_context import DeviceContext
from services.network.netmiko.platform import UnsupportedPlatformError
from workflow_steps.common.device_type import connection_device_type

STEPS = Path(__file__).resolve().parents[2] / "workflow_steps"


def _device(**fields: str | None) -> DeviceContext:
    return DeviceContext(id="d", name="d", hostname="d", **fields)


def test_the_network_driver_decides() -> None:
    assert connection_device_type(_device(network_driver="cisco_ios"), None) == "cisco_ios"


def test_the_platform_is_used_when_there_is_no_driver() -> None:
    assert connection_device_type(_device(platform="IOS-XE"), None) == "cisco_xe"


def test_the_driver_wins_over_the_platform() -> None:
    device = _device(network_driver="arista_eos", platform="cisco_ios")
    assert connection_device_type(device, None) == "arista_eos"


def test_an_override_wins_over_both_and_is_normalised() -> None:
    device = _device(network_driver="cisco_ios", platform="cisco_ios")
    assert connection_device_type(device, " NXOS ") == "cisco_nxos"
    assert connection_device_type(device, "some_netmiko_type") == "some_netmiko_type"


def test_a_blank_override_means_no_override() -> None:
    assert connection_device_type(_device(network_driver="cisco_ios"), "  ") == "cisco_ios"


def test_an_unknown_platform_raises_with_its_failure_record() -> None:
    with pytest.raises(UnsupportedPlatformError) as caught:
        connection_device_type(_device(network_driver="no-such-os"), None)
    assert caught.value.failure.kind == "unsupported_platform"


def test_no_step_calls_the_platform_resolver_itself() -> None:
    offenders = [
        str(path.relative_to(STEPS))
        for path in STEPS.rglob("*.py")
        if path.name != "device_type.py"
        and "resolve_connection_device_type(" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
