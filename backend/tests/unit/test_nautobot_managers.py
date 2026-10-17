"""Unit tests for services/nautobot/managers/* against mocked collaborators.

No network: ``nautobot_service`` is a MagicMock with ``rest_request`` /
``graphql_query`` AsyncMocks; resolvers are MagicMocks with AsyncMock methods.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.nautobot.common.exceptions import NautobotAPIError
from services.nautobot.managers.device_manager import DeviceManager
from services.nautobot.managers.interface_manager import InterfaceManager
from services.nautobot.managers.ip_manager import IPManager
from services.nautobot.managers.prefix_manager import (
    PrefixManager,
    _attach_optional_location,
    _find_prefix_id,
    _resolve_namespace_ref,
)

_UUID = "550e8400-e29b-41d4-a716-446655440000"


def _nautobot() -> MagicMock:
    svc = MagicMock()
    svc.rest_request = AsyncMock()
    svc.graphql_query = AsyncMock()
    return svc


def _metadata_resolver(status_id: str = "status-uuid") -> MagicMock:
    resolver = MagicMock()
    resolver.resolve_status_id = AsyncMock(return_value=status_id)
    resolver.resolve_location_id = AsyncMock(return_value="loc-uuid")
    return resolver


class IPManagerTests(unittest.IsolatedAsyncioTestCase):
    def _manager(self, nautobot: MagicMock) -> IPManager:
        return IPManager(nautobot, MagicMock(), _metadata_resolver())

    async def test_returns_existing_ip_without_creating(self) -> None:
        nautobot = _nautobot()
        nautobot.rest_request.return_value = {"count": 1, "results": [{"id": "existing-ip"}]}
        result = await self._manager(nautobot).ensure_ip_address_exists("10.0.0.1/24", "ns")
        self.assertEqual(result, "existing-ip")
        self.assertEqual(nautobot.rest_request.await_count, 1)

    async def test_creates_ip_when_absent(self) -> None:
        nautobot = _nautobot()
        nautobot.rest_request.side_effect = [{"count": 0}, {"id": "new-ip"}]
        result = await self._manager(nautobot).ensure_ip_address_exists("10.0.0.1/24", "ns")
        self.assertEqual(result, "new-ip")
        create_call = nautobot.rest_request.await_args_list[1]
        self.assertEqual(create_call.kwargs["method"], "POST")
        self.assertEqual(create_call.kwargs["data"]["status"], "status-uuid")

    async def test_duplicate_host_error_reuses_existing_ip(self) -> None:
        nautobot = _nautobot()
        nautobot.rest_request.side_effect = [
            {"count": 0},
            NautobotAPIError("IP address with this Parent and Host already exists"),
            {"count": 1, "results": [{"id": "found-ip", "address": "10.0.0.1/32"}]},
        ]
        result = await self._manager(nautobot).ensure_ip_address_exists(
            "10.0.0.1/24", "ns", use_assigned_ip_if_exists=True
        )
        self.assertEqual(result, "found-ip")

    async def test_missing_prefix_without_autocreate_raises(self) -> None:
        nautobot = _nautobot()
        nautobot.rest_request.side_effect = [
            {"count": 0},
            NautobotAPIError("No suitable parent Prefix exists"),
        ]
        with self.assertRaises(NautobotAPIError):
            await self._manager(nautobot).ensure_ip_address_exists("10.0.0.1/24", "ns")

    async def test_unrelated_create_error_propagates(self) -> None:
        nautobot = _nautobot()
        boom = NautobotAPIError("permission denied")
        nautobot.rest_request.side_effect = [{"count": 0}, boom]
        with self.assertRaises(NautobotAPIError) as ctx:
            await self._manager(nautobot).ensure_ip_address_exists("10.0.0.1/24", "ns")
        self.assertIs(ctx.exception, boom)

    async def test_missing_prefix_autocreate_retries_after_prefix(self) -> None:
        nautobot = _nautobot()
        nautobot.rest_request.side_effect = [
            {"count": 0},  # _find_ip_by_address
            NautobotAPIError("No suitable parent Prefix exists"),  # first create
            {"id": "retried-ip"},  # create after prefix
        ]
        with patch(
            "services.nautobot.managers.prefix_manager.PrefixManager"
        ) as prefix_cls:
            prefix_cls.return_value.ensure_prefix_exists = AsyncMock(return_value="px")
            result = await self._manager(nautobot).ensure_ip_address_exists(
                "10.0.0.1/24", "ns", add_prefixes_automatically=True
            )
        self.assertEqual(result, "retried-ip")

    async def test_find_existing_ip_by_host_raises_when_absent(self) -> None:
        nautobot = _nautobot()
        nautobot.rest_request.side_effect = [
            {"count": 0},
            NautobotAPIError("IP address with this Parent and Host already exists"),
            {"count": 0},
        ]
        with self.assertRaises(NautobotAPIError):
            await self._manager(nautobot).ensure_ip_address_exists(
                "10.0.0.1/24", "ns", use_assigned_ip_if_exists=True
            )

    async def test_assign_ip_to_interface_returns_existing_association(self) -> None:
        nautobot = _nautobot()
        nautobot.rest_request.return_value = {"count": 1, "results": [{"id": "assoc"}]}
        result = await self._manager(nautobot).assign_ip_to_interface("ip", "if")
        self.assertEqual(result, {"id": "assoc"})

    async def test_assign_ip_to_interface_creates_new_association(self) -> None:
        nautobot = _nautobot()
        nautobot.rest_request.side_effect = [{"count": 0}, {"id": "assoc-new"}]
        result = await self._manager(nautobot).assign_ip_to_interface("ip", "if", is_primary=True)
        self.assertEqual(result, {"id": "assoc-new"})
        post_call = nautobot.rest_request.await_args_list[1]
        self.assertEqual(post_call.kwargs["data"]["is_primary"], True)


class InterfaceManagerTests(unittest.IsolatedAsyncioTestCase):
    def _manager(
        self, nautobot: MagicMock, ip_manager: MagicMock | None = None
    ) -> InterfaceManager:
        network_resolver = MagicMock()
        network_resolver.resolve_namespace_id = AsyncMock(return_value="ns-uuid")
        return InterfaceManager(
            nautobot, network_resolver, _metadata_resolver(), ip_manager or MagicMock()
        )

    async def test_ensure_interface_exists_returns_existing(self) -> None:
        nautobot = _nautobot()
        nautobot.rest_request.return_value = {"count": 1, "results": [{"id": "if-existing"}]}
        result = await self._manager(nautobot).ensure_interface_exists("dev", "Gi0/0")
        self.assertEqual(result, "if-existing")

    async def test_ensure_interface_exists_creates_new(self) -> None:
        nautobot = _nautobot()
        nautobot.rest_request.side_effect = [{"count": 0}, {"id": "if-new"}]
        result = await self._manager(nautobot).ensure_interface_exists("dev", "Gi0/0")
        self.assertEqual(result, "if-new")
        post_call = nautobot.rest_request.await_args_list[1]
        self.assertEqual(post_call.kwargs["data"]["status"], "status-uuid")

    async def test_ensure_interface_with_ip_orchestration(self) -> None:
        nautobot = _nautobot()
        nautobot.rest_request.return_value = {"count": 1, "results": [{"id": "if1"}]}
        ip_manager = MagicMock()
        ip_manager.ensure_ip_address_exists = AsyncMock(return_value="ip1")
        ip_manager.assign_ip_to_interface = AsyncMock(return_value={})
        mgr = self._manager(nautobot, ip_manager)
        result = await mgr.ensure_interface_with_ip("dev", "10.0.0.1/24")
        self.assertEqual(result, "ip1")
        ip_manager.assign_ip_to_interface.assert_awaited_once()

    async def test_update_interface_ip_without_old_ip_falls_back_to_loopback(self) -> None:
        nautobot = _nautobot()
        nautobot.rest_request.return_value = {"count": 1, "results": [{"id": "if1"}]}
        ip_manager = MagicMock()
        ip_manager.ensure_ip_address_exists = AsyncMock(return_value="ip-new")
        ip_manager.assign_ip_to_interface = AsyncMock(return_value={})
        mgr = self._manager(nautobot, ip_manager)
        result = await mgr.update_interface_ip("dev", "r1", None, "10.0.0.2/24", "Global")
        self.assertEqual(result, "ip-new")

    async def test_update_interface_ip_with_found_interface(self) -> None:
        nautobot = _nautobot()
        ip_manager = MagicMock()
        ip_manager.ensure_ip_address_exists = AsyncMock(return_value="ip-updated")
        ip_manager.assign_ip_to_interface = AsyncMock(return_value={})
        mgr = self._manager(nautobot, ip_manager)
        with patch(
            "services.nautobot.resolvers.device_resolver.DeviceResolver"
        ) as resolver_cls:
            resolver_cls.return_value.find_interface_with_ip = AsyncMock(
                return_value=("if1", "Gi0/0")
            )
            result = await mgr.update_interface_ip(
                "dev", "r1", "10.0.0.1/24", "10.0.0.2/24", "Global"
            )
        self.assertEqual(result, "ip-updated")
        ip_manager.assign_ip_to_interface.assert_awaited_once_with(
            ip_id="ip-updated", interface_id="if1"
        )


class PrefixManagerModuleHelpersTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_namespace_ref_passthrough_uuid(self) -> None:
        resolver = MagicMock()
        resolver.resolve_namespace_id = AsyncMock()
        self.assertEqual(await _resolve_namespace_ref(resolver, _UUID), _UUID)
        resolver.resolve_namespace_id.assert_not_called()

    async def test_resolve_namespace_ref_resolves_name(self) -> None:
        resolver = MagicMock()
        resolver.resolve_namespace_id = AsyncMock(return_value="ns-uuid")
        self.assertEqual(await _resolve_namespace_ref(resolver, "Global"), "ns-uuid")

    async def test_find_prefix_id_hit_and_miss(self) -> None:
        nautobot = _nautobot()
        nautobot.rest_request.return_value = {"count": 1, "results": [{"id": "px1"}]}
        self.assertEqual(await _find_prefix_id(nautobot, "10.0.0.0/24", "ns"), "px1")
        nautobot.rest_request.return_value = {"count": 0}
        self.assertIsNone(await _find_prefix_id(nautobot, "10.0.0.0/24", "ns"))

    async def test_attach_optional_location_uuid_passthrough(self) -> None:
        data: dict = {}
        await _attach_optional_location(MagicMock(), data, _UUID)
        self.assertEqual(data["location"], _UUID)

    async def test_attach_optional_location_resolves_name(self) -> None:
        resolver = MagicMock()
        resolver.resolve_location_id = AsyncMock(return_value="loc-uuid")
        data: dict = {}
        await _attach_optional_location(resolver, data, "dc1")
        self.assertEqual(data["location"], "loc-uuid")

    async def test_attach_optional_location_missing_name_leaves_data_clean(self) -> None:
        resolver = MagicMock()
        resolver.resolve_location_id = AsyncMock(return_value=None)
        data: dict = {}
        await _attach_optional_location(resolver, data, "ghost")
        self.assertNotIn("location", data)


class PrefixManagerTests(unittest.IsolatedAsyncioTestCase):
    def _manager(self, nautobot: MagicMock) -> PrefixManager:
        network_resolver = MagicMock()
        network_resolver.resolve_namespace_id = AsyncMock(return_value="ns-uuid")
        return PrefixManager(nautobot, network_resolver, _metadata_resolver())

    async def test_returns_existing_prefix(self) -> None:
        nautobot = _nautobot()
        nautobot.rest_request.return_value = {"count": 1, "results": [{"id": "px-existing"}]}
        result = await self._manager(nautobot).ensure_prefix_exists("10.0.0.0/24")
        self.assertEqual(result, "px-existing")

    async def test_creates_prefix_with_description(self) -> None:
        nautobot = _nautobot()
        nautobot.rest_request.side_effect = [{"count": 0}, {"id": "px-new"}]
        result = await self._manager(nautobot).ensure_prefix_exists(
            "10.0.0.0/24", description="auto"
        )
        self.assertEqual(result, "px-new")
        post_call = nautobot.rest_request.await_args_list[1]
        self.assertEqual(post_call.kwargs["data"]["description"], "auto")
        self.assertEqual(post_call.kwargs["data"]["status"], "status-uuid")

    async def test_creates_prefix_with_resolved_location(self) -> None:
        nautobot = _nautobot()
        nautobot.rest_request.side_effect = [{"count": 0}, {"id": "px-new"}]
        result = await self._manager(nautobot).ensure_prefix_exists(
            "10.0.0.0/24", location="dc1"
        )
        self.assertEqual(result, "px-new")
        post_call = nautobot.rest_request.await_args_list[1]
        self.assertEqual(post_call.kwargs["data"]["location"], "loc-uuid")

    async def test_create_without_id_raises(self) -> None:
        nautobot = _nautobot()
        nautobot.rest_request.side_effect = [{"count": 0}, {}]
        with self.assertRaises(NautobotAPIError):
            await self._manager(nautobot).ensure_prefix_exists("10.0.0.0/24")

    async def test_uuid_namespace_skips_resolver(self) -> None:
        nautobot = _nautobot()
        nautobot.rest_request.return_value = {"count": 1, "results": [{"id": "px"}]}
        mgr = self._manager(nautobot)
        await mgr.ensure_prefix_exists("10.0.0.0/24", namespace=_UUID)
        mgr.network_resolver.resolve_namespace_id.assert_not_called()


class DeviceManagerTests(unittest.IsolatedAsyncioTestCase):
    def _manager(self, nautobot: MagicMock) -> DeviceManager:
        return DeviceManager(nautobot, MagicMock(), MagicMock())

    async def test_get_device_details_depth_zero(self) -> None:
        nautobot = _nautobot()
        nautobot.rest_request.return_value = {"name": "r1"}
        await self._manager(nautobot).get_device_details("dev")
        self.assertEqual(
            nautobot.rest_request.await_args.kwargs["endpoint"], "dcim/devices/dev/"
        )

    async def test_get_device_details_with_depth(self) -> None:
        nautobot = _nautobot()
        nautobot.rest_request.return_value = {"name": "r1"}
        await self._manager(nautobot).get_device_details("dev", depth=2)
        self.assertIn("depth=2", nautobot.rest_request.await_args.kwargs["endpoint"])

    async def test_extract_primary_ip_none(self) -> None:
        nautobot = _nautobot()
        self.assertIsNone(await self._manager(nautobot).extract_primary_ip_address({}))

    async def test_extract_primary_ip_dict_form(self) -> None:
        nautobot = _nautobot()
        result = await self._manager(nautobot).extract_primary_ip_address(
            {"primary_ip4": {"address": "10.0.0.1/24"}}
        )
        self.assertEqual(result, "10.0.0.1/24")

    async def test_extract_primary_ip_uuid_form_fetches_details(self) -> None:
        nautobot = _nautobot()
        nautobot.rest_request.return_value = {"address": "10.0.0.9/24"}
        result = await self._manager(nautobot).extract_primary_ip_address(
            {"primary_ip4": _UUID}
        )
        self.assertEqual(result, "10.0.0.9/24")

    async def test_extract_primary_ip_uuid_form_handles_api_error(self) -> None:
        nautobot = _nautobot()
        nautobot.rest_request.side_effect = NautobotAPIError("boom")
        result = await self._manager(nautobot).extract_primary_ip_address(
            {"primary_ip4": _UUID}
        )
        self.assertIsNone(result)

    async def test_extract_primary_ip_unexpected_type(self) -> None:
        nautobot = _nautobot()
        self.assertIsNone(
            await self._manager(nautobot).extract_primary_ip_address({"primary_ip4": 12345})
        )

    async def test_assign_primary_ip_success(self) -> None:
        nautobot = _nautobot()
        nautobot.rest_request.return_value = {}
        self.assertTrue(
            await self._manager(nautobot).assign_primary_ip_to_device("dev", "ip")
        )

    async def test_assign_primary_ip_failure(self) -> None:
        nautobot = _nautobot()
        nautobot.rest_request.side_effect = NautobotAPIError("boom")
        self.assertFalse(
            await self._manager(nautobot).assign_primary_ip_to_device("dev", "ip")
        )

    async def test_verify_device_updates_all_match(self) -> None:
        ok, mismatches = await self._manager(_nautobot()).verify_device_updates(
            "dev", {"serial": "SN1"}, {"serial": "SN1"}
        )
        self.assertTrue(ok)
        self.assertEqual(mismatches, [])

    async def test_verify_device_updates_custom_field_mismatch(self) -> None:
        ok, mismatches = await self._manager(_nautobot()).verify_device_updates(
            "dev",
            {"custom_fields": {"site_code": "NYC1"}},
            {"custom_fields": {"site_code": "LON1"}},
        )
        self.assertFalse(ok)
        self.assertEqual(mismatches[0]["field"], "custom_fields.site_code")

    async def test_verify_device_updates_skips_tags(self) -> None:
        ok, mismatches = await self._manager(_nautobot()).verify_device_updates(
            "dev", {"tags": ["a"]}, {"tags": [{"name": "b"}]}
        )
        self.assertTrue(ok)

    async def test_verify_device_updates_extracts_nested_id(self) -> None:
        ok, _ = await self._manager(_nautobot()).verify_device_updates(
            "dev", {"primary_ip4": "ip-uuid"}, {"primary_ip4": {"id": "ip-uuid"}}
        )
        self.assertTrue(ok)

    async def test_verify_device_updates_extracts_choice_value(self) -> None:
        ok, _ = await self._manager(_nautobot()).verify_device_updates(
            "dev", {"face": "front"}, {"face": {"value": "front", "label": "Front"}}
        )
        self.assertTrue(ok)

    async def test_verify_device_updates_str_equal_normalization(self) -> None:
        ok, _ = await self._manager(_nautobot()).verify_device_updates(
            "dev", {"position": "10"}, {"position": 10}
        )
        self.assertTrue(ok)

    async def test_verify_device_updates_records_plain_mismatch(self) -> None:
        ok, mismatches = await self._manager(_nautobot()).verify_device_updates(
            "dev", {"serial": "SN1"}, {"serial": "SN2"}
        )
        self.assertFalse(ok)
        self.assertEqual(mismatches[0], {"field": "serial", "expected": "SN1", "actual": "SN2"})


if __name__ == "__main__":
    unittest.main()
