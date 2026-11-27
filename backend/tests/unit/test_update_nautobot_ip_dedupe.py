"""W5-03 / D6: update-nautobot-ip (Update IP) writes one IP address once per distinct change.

Devices that resolve to the same IP address with the same values share one write and its
result, like Update VLAN and Update IP Prefix; different values of one address run one after
the other, different addresses concurrently.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.nautobot.common.exceptions import NautobotAPIError
from tests.unit.test_update_nautobot_ip_executor import _IP_ID, _config, _context, _device, _run

pytestmark = pytest.mark.asyncio

_OTHER_IP = "66666666-6666-6666-6666-666666666666"


async def test_devices_of_one_address_and_values_share_one_write() -> None:
    out, common = await _run(_config(), _context(_device("a"), _device("b"), _device("c")))

    assert common.update_ip_address.await_count == 1
    assert sorted(out["success"].devices) == ["a", "b", "c"]
    counts = out["success"].metadata["n1.update_ip_counts"]
    assert counts == {"updated": 3, "unchanged": 0, "failed": 0}


async def test_a_failed_shared_write_fails_every_device_of_the_group() -> None:
    common = MagicMock()
    common.update_ip_address = AsyncMock(side_effect=NautobotAPIError("refused", http_status=400))
    out, _ = await _run(_config(), _context(_device("a"), _device("b")), common=common)

    assert common.update_ip_address.await_count == 1
    assert sorted(out["failure"].devices) == ["a", "b"]
    assert all(device.errors for device in out["failure"].devices.values())


async def test_different_addresses_are_written_separately() -> None:
    a = _device("a", attribute_bags={"custom": {"ip_id": _IP_ID}})
    b = _device("b", attribute_bags={"custom": {"ip_id": _OTHER_IP}})
    out, common = await _run(_config(ip_id="{custom.ip_id}"), _context(a, b))

    assert common.update_ip_address.await_count == 2
    assert sorted(out["success"].devices) == ["a", "b"]


async def test_two_value_sets_of_one_address_do_not_run_at_once() -> None:
    running = peak = 0

    async def update(*_args, **_kwargs) -> bool:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return True

    common = MagicMock()
    common.update_ip_address = AsyncMock(side_effect=update)
    a = _device("a", attribute_bags={"custom": {"text": "one"}})
    b = _device("b", attribute_bags={"custom": {"text": "two"}})
    out, _ = await _run(_config(description="{custom.text}"), _context(a, b), common=common)

    assert common.update_ip_address.await_count == 2
    assert peak == 1
    assert sorted(out["success"].devices) == ["a", "b"]


async def test_one_address_moved_to_two_namespaces_is_not_one_write() -> None:
    """Each device moves the address to a prefix of its own namespace: no shared result."""
    namespaces = {"Lab": "77777777-7777-7777-7777-777777777777", "Prod": _OTHER_IP}
    common = MagicMock()
    common.resolve_namespace_id = AsyncMock(side_effect=lambda name: namespaces[name])
    a = _device("a", attribute_bags={"custom": {"ns": "Lab"}})
    b = _device("b", attribute_bags={"custom": {"ns": "Prod"}})
    out, common = await _run(
        {"nautobot_source_id": "s", "ip_id": _IP_ID, "namespace": "{custom.ns}"},
        _context(a, b),
        common=common,
    )

    assert common.update_ip_address.await_count == 2
    assert sorted(out["success"].devices) == ["a", "b"]
