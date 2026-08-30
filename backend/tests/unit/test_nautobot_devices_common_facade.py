"""Unit tests for the DeviceCommonService facade and NautobotMetadataService.

The facade only wires + delegates; components are patched with AsyncMock stand-ins
so every delegation line is exercised without touching real resolvers/managers.
"""

from __future__ import annotations

import unittest
from unittest.mock import DEFAULT, AsyncMock, MagicMock, patch

from services.nautobot.devices.common import DeviceCommonService
from services.nautobot.metadata_service import NautobotMetadataService

_COMPONENTS = [
    "DeviceResolver",
    "MetadataResolver",
    "NetworkResolver",
    "IPManager",
    "PrefixManager",
    "InterfaceManager",
    "DeviceManager",
]


class FacadeLazyLoadingTests(unittest.TestCase):
    def test_components_are_lazy_and_cached(self) -> None:
        with patch.multiple(
            "services.nautobot.devices.common",
            **{name: DEFAULT for name in _COMPONENTS},
        ):
            facade = DeviceCommonService(MagicMock())
            self.assertIsNone(facade._device_resolver)
            first = facade.device_resolver
            self.assertIs(first, facade.device_resolver)  # cached
            # touching a manager lazily builds its resolver deps too
            self.assertIsNotNone(facade.interface_manager)
            self.assertIsNotNone(facade.ip_manager)
            self.assertIsNotNone(facade.prefix_manager)
            self.assertIsNotNone(facade.device_manager)
            self.assertIsNotNone(facade.metadata_resolver)
            self.assertIsNotNone(facade.network_resolver)


class FacadeDelegationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        patcher = patch.multiple(
            "services.nautobot.devices.common",
            **{name: DEFAULT for name in _COMPONENTS},
        )
        self.addCleanup(patcher.stop)
        self.mocks = patcher.start()
        for name in _COMPONENTS:
            self.mocks[name].return_value = AsyncMock()
        self.facade = DeviceCommonService(MagicMock())

    async def test_device_resolution_delegations(self) -> None:
        dr = self.mocks["DeviceResolver"].return_value
        await self.facade.resolve_device_by_name("r1")
        dr.resolve_device_by_name.assert_awaited_once_with("r1")
        await self.facade.resolve_device_by_ip("10.0.0.1")
        dr.resolve_device_by_ip.assert_awaited_once_with("10.0.0.1")
        await self.facade.resolve_device_id(device_name="r1")
        dr.resolve_device_id.assert_awaited_once()
        await self.facade.find_interface_with_ip("r1", "10.0.0.1/24")
        dr.find_interface_with_ip.assert_awaited_once_with("r1", "10.0.0.1/24")
        await self.facade.resolve_device_type_id("C9300", "Cisco")
        dr.resolve_device_type_id.assert_awaited_once_with("C9300", "Cisco")
        await self.facade.get_device_type_display("dt")
        dr.get_device_type_display.assert_awaited_once_with("dt")

    async def test_metadata_resolution_delegations(self) -> None:
        mr = self.mocks["MetadataResolver"].return_value
        await self.facade.resolve_status_id("active")
        mr.resolve_status_id.assert_awaited_once_with("active", "dcim.device")
        await self.facade.resolve_role_id("leaf")
        await self.facade.resolve_platform_id("ios")
        await self.facade.get_platform_name("p")
        await self.facade.resolve_location_id("dc1")
        await self.facade.resolve_rack_id("A1", location="dc1")
        mr.resolve_rack_id.assert_awaited_once_with("A1", location="dc1")

    async def test_network_resolution_delegations(self) -> None:
        nr = self.mocks["NetworkResolver"].return_value
        await self.facade.resolve_namespace_id("Global")
        await self.facade.resolve_ip_address("10.0.0.1/24", "ns")
        await self.facade.resolve_interface_by_name("dev", "Gi0/0")
        nr.resolve_interface_by_name.assert_awaited_once_with("dev", "Gi0/0")

    async def test_manager_delegations(self) -> None:
        ip = self.mocks["IPManager"].return_value
        px = self.mocks["PrefixManager"].return_value
        iface = self.mocks["InterfaceManager"].return_value
        dev = self.mocks["DeviceManager"].return_value
        await self.facade.ensure_ip_address_exists("10.0.0.1/24", "ns")
        ip.ensure_ip_address_exists.assert_awaited_once()
        await self.facade.assign_ip_to_interface("ip", "if")
        ip.assign_ip_to_interface.assert_awaited_once_with("ip", "if", False)
        await self.facade.ensure_prefix_exists("10.0.0.0/24")
        px.ensure_prefix_exists.assert_awaited_once()
        await self.facade.ensure_interface_exists("dev", "Gi0/0")
        await self.facade.ensure_interface_with_ip("dev", "10.0.0.1/24")
        await self.facade.update_interface_ip("dev", "r1", None, "10.0.0.2/24", "Global")
        iface.update_interface_ip.assert_awaited_once()
        await self.facade.get_device_details("dev", 1)
        await self.facade.extract_primary_ip_address({"primary_ip4": None})
        await self.facade.assign_primary_ip_to_device("dev", "ip")
        await self.facade.verify_device_updates("dev", {}, {})
        dev.verify_device_updates.assert_awaited_once_with("dev", {}, {})

    def test_pure_function_delegations(self) -> None:
        self.assertTrue(self.facade.validate_ip_address("10.0.0.1"))
        self.assertFalse(self.facade.validate_mac_address("nope"))
        self.assertTrue(self.facade._is_valid_uuid("550e8400-e29b-41d4-a716-446655440000"))
        self.facade.validate_required_fields({"a": 1}, ["a"])
        self.assertEqual(
            self.facade.flatten_nested_fields({"platform.name": "ios"}), {"platform": "ios"}
        )
        self.assertEqual(
            self.facade.extract_nested_value({"p": {"n": "ios"}}, "p.n"), "ios"
        )
        self.assertEqual(self.facade.normalize_tags("a,b"), ["a", "b"])
        data, _iface, _ns = self.facade.prepare_update_data({"status": "active"}, ["status"])
        self.assertEqual(data, {"status": "active"})
        self.assertTrue(self.facade.is_duplicate_error(Exception("already exists")))
        payload = self.facade.handle_already_exists_error(Exception("x"), "Device")
        self.assertEqual(payload["error"], "already_exists")


class NautobotMetadataServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_device_custom_fields_unwraps_results(self) -> None:
        nautobot = MagicMock()
        nautobot.rest_request = AsyncMock(return_value={"results": [{"key": "site_code"}]})
        svc = NautobotMetadataService(nautobot, MagicMock())
        self.assertEqual(await svc.get_device_custom_fields(), [{"key": "site_code"}])
        endpoint = nautobot.rest_request.await_args.args[0]
        self.assertIn("content_types=dcim.device", endpoint)

    async def test_get_custom_field_choices_unwraps_results(self) -> None:
        nautobot = MagicMock()
        nautobot.rest_request = AsyncMock(return_value={})
        svc = NautobotMetadataService(nautobot, MagicMock())
        self.assertEqual(await svc.get_custom_field_choices("site_code"), [])


if __name__ == "__main__":
    unittest.main()
