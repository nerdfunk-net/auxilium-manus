"""Tests for the delete operations of DeviceManager and IPManager."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from services.nautobot.managers.device_manager import DeviceManager
from services.nautobot.managers.ip_manager import IPManager

_DEV = "11111111-1111-1111-1111-111111111111"
_IF1 = "10000000-0000-0000-0000-000000000001"
_IF2 = "10000000-0000-0000-0000-000000000002"
_IF_OTHER = "20000000-0000-0000-0000-000000000009"
_IP_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_IP_SHARED = "cccccccc-cccc-cccc-cccc-cccccccccccc"


class DeviceManagerDeleteTests(unittest.IsolatedAsyncioTestCase):
    async def test_deletes_by_uuid(self) -> None:
        nautobot = MagicMock()
        nautobot.rest_request = AsyncMock(return_value={"status": "success"})
        await DeviceManager(nautobot, MagicMock(), MagicMock()).delete_device(_DEV.upper())
        nautobot.rest_request.assert_awaited_once_with(
            endpoint=f"dcim/devices/{_DEV.upper()}/", method="DELETE"
        )

    async def test_rejects_non_uuid_without_a_request(self) -> None:
        nautobot = MagicMock()
        nautobot.rest_request = AsyncMock()
        with self.assertRaises(ValueError):
            await DeviceManager(nautobot, MagicMock(), MagicMock()).delete_device("sw1")
        nautobot.rest_request.assert_not_awaited()


def _assignment(ip: str, interface: str | None, vm: str | None = None) -> dict:
    return {
        "ip_address": {"id": ip},
        "interface": interface and {"id": interface},
        "vm_interface": vm,
    }


class IPManagerDeviceIpTests(unittest.IsolatedAsyncioTestCase):
    def _manager(self, routes: dict[str, dict]) -> tuple[IPManager, MagicMock]:
        nautobot = MagicMock()

        async def rest_request(*, endpoint: str, method: str = "GET", data=None):
            for needle, response in routes.items():
                if needle in endpoint:
                    return response
            raise AssertionError(endpoint)

        nautobot.rest_request = AsyncMock(side_effect=rest_request)
        return IPManager(nautobot, MagicMock(), MagicMock()), nautobot

    async def test_splits_owned_and_shared_ips(self) -> None:
        manager, _ = self._manager(
            {
                "dcim/interfaces/": {"results": [{"id": _IF1}, {"id": _IF2}]},
                f"interface={_IF1}": {"results": [_assignment(_IP_A, _IF1)]},
                f"interface={_IF2}": {"results": [_assignment(_IP_SHARED, _IF2)]},
                f"ip_address={_IP_A}": {"results": [_assignment(_IP_A, _IF1)]},
                f"ip_address={_IP_SHARED}": {
                    "results": [_assignment(_IP_SHARED, _IF2), _assignment(_IP_SHARED, _IF_OTHER)]
                },
            }
        )
        owned, shared = await manager.list_device_ip_ids(_DEV)
        self.assertEqual(owned, [_IP_A])
        self.assertEqual(shared, [_IP_SHARED])

    async def test_vm_interface_assignment_counts_as_shared(self) -> None:
        manager, _ = self._manager(
            {
                "dcim/interfaces/": {"results": [{"id": _IF1}]},
                f"interface={_IF1}": {"results": [_assignment(_IP_A, _IF1)]},
                f"ip_address={_IP_A}": {
                    "results": [_assignment(_IP_A, _IF1), _assignment(_IP_A, None, vm="vm-if")]
                },
            }
        )
        owned, shared = await manager.list_device_ip_ids(_DEV)
        self.assertEqual((owned, shared), ([], [_IP_A]))

    async def test_empty_ip_lookup_is_not_exclusive(self) -> None:
        # The address was found through our interface, but the follow-up lookup returns nothing
        # (a race with an unassignment): never delete on an unconfirmed answer.
        manager, _ = self._manager(
            {
                "dcim/interfaces/": {"results": [{"id": _IF1}]},
                f"interface={_IF1}": {"results": [_assignment(_IP_A, _IF1)]},
                f"ip_address={_IP_A}": {"results": []},
            }
        )
        self.assertEqual(await manager.list_device_ip_ids(_DEV), ([], [_IP_A]))

    async def test_device_without_interfaces(self) -> None:
        manager, _ = self._manager({"dcim/interfaces/": {"results": []}})
        self.assertEqual(await manager.list_device_ip_ids(_DEV), ([], []))

    async def test_delete_ip_address(self) -> None:
        manager, nautobot = self._manager({})
        nautobot.rest_request = AsyncMock(return_value={"status": "success"})
        await manager.delete_ip_address(_IP_A)
        nautobot.rest_request.assert_awaited_once_with(
            endpoint=f"ipam/ip-addresses/{_IP_A}/", method="DELETE"
        )

    async def test_delete_ip_address_rejects_non_uuid(self) -> None:
        manager, _ = self._manager({})
        with self.assertRaises(ValueError):
            await manager.delete_ip_address("10.0.0.1")
