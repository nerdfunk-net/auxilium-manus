"""Unit tests for services/nautobot/devices/interface_workflow.py.

``self.common`` (a DeviceCommonService) and ``self.nautobot`` are replaced with
mocks; no network. REST calls are dispatched by a small fake keyed on
(method, endpoint-substring).
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from services.nautobot.devices.interface_workflow import (
    InterfaceManagerService,
    _build_interface_payload,
    _InterfaceUpdateState,
    _ip_map_key,
    _normalize_interface_ip_list,
    _normalize_interface_type,
    _resolve_tagged_vlan_ids,
    _resolve_untagged_vlan_id,
)


class PureHelperTests(unittest.TestCase):
    def test_normalize_interface_ip_list_passthrough(self) -> None:
        iface = {"ip_addresses": [{"address": "10.0.0.1/24"}]}
        self.assertEqual(_normalize_interface_ip_list(iface), [{"address": "10.0.0.1/24"}])

    def test_normalize_interface_ip_list_converts_single_field(self) -> None:
        iface = {"ip_address": "10.0.0.1/24", "namespace": "Mgmt", "ip_role": "Secondary"}
        self.assertEqual(
            _normalize_interface_ip_list(iface),
            [{"address": "10.0.0.1/24", "namespace": "Mgmt", "ip_role": "Secondary"}],
        )

    def test_normalize_interface_ip_list_empty(self) -> None:
        self.assertEqual(_normalize_interface_ip_list({"name": "x"}), [])

    def test_ip_map_key(self) -> None:
        self.assertEqual(_ip_map_key("Gi0/0", "10.0.0.1/24"), "Gi0/0:10.0.0.1/24")

    def test_normalize_interface_type_lowercases(self) -> None:
        self.assertEqual(_normalize_interface_type({"name": "x", "type": "Virtual"}, []), "virtual")

    def test_normalize_interface_type_missing_warns(self) -> None:
        warnings: list[str] = []
        self.assertIsNone(_normalize_interface_type({"name": "x", "type": ""}, warnings))
        self.assertEqual(len(warnings), 1)

    def test_build_interface_payload_optional_fields_and_vlans(self) -> None:
        payload = _build_interface_payload(
            device_id="d1",
            interface={
                "name": "Gi0/0",
                "enabled": True,
                "mtu": 1500,
                "mode": "none",  # dropped
                "description": None,  # dropped
            },
            interface_type="virtual",
            interface_status_id="st1",
            untagged_vlan_id="vl1",
            tagged_vlan_ids=["vl2", "vl3"],
        )
        self.assertEqual(payload["device"], "d1")
        self.assertEqual(payload["status"], "st1")
        self.assertEqual(payload["enabled"], True)
        self.assertEqual(payload["mtu"], 1500)
        self.assertNotIn("mode", payload)
        self.assertNotIn("description", payload)
        self.assertEqual(payload["untagged_vlan"], {"id": "vl1"})
        self.assertEqual(payload["tagged_vlans"], [{"id": "vl2"}, {"id": "vl3"}])

    def test_build_interface_payload_omits_untagged_vlan_when_id_is_none(self) -> None:
        payload = _build_interface_payload(
            device_id="d1",
            interface={"name": "Gi0/0"},
            interface_type="virtual",
            interface_status_id="st1",
            untagged_vlan_id=None,
            tagged_vlan_ids=[],
        )
        self.assertNotIn("untagged_vlan", payload)
        self.assertNotIn("tagged_vlans", payload)


class ResolveUntaggedVlanIdTests(unittest.IsolatedAsyncioTestCase):
    def _common(self) -> MagicMock:
        common = MagicMock()
        common.ensure_vlan_exists = AsyncMock(return_value="vlan-uuid")
        return common

    async def test_missing_returns_none(self) -> None:
        common = self._common()
        result = await _resolve_untagged_vlan_id(
            common=common, interface={"name": "Gi0/0"}, device_location_id=None, warnings=[]
        )
        self.assertIsNone(result)
        common.ensure_vlan_exists.assert_not_awaited()

    async def test_none_sentinel_returns_none(self) -> None:
        common = self._common()
        result = await _resolve_untagged_vlan_id(
            common=common,
            interface={"name": "Gi0/0", "untagged_vlan": "none"},
            device_location_id=None,
            warnings=[],
        )
        self.assertIsNone(result)
        common.ensure_vlan_exists.assert_not_awaited()

    async def test_already_uuid_passes_through_without_resolving(self) -> None:
        common = self._common()
        result = await _resolve_untagged_vlan_id(
            common=common,
            interface={"name": "Gi0/0", "untagged_vlan": "3542814a-d33f-4cc3-bfdd-eb3a35945b31"},
            device_location_id=None,
            warnings=[],
        )
        self.assertEqual(result, "3542814a-d33f-4cc3-bfdd-eb3a35945b31")
        common.ensure_vlan_exists.assert_not_awaited()

    async def test_raw_vid_resolved_via_ensure_vlan_exists(self) -> None:
        common = self._common()
        result = await _resolve_untagged_vlan_id(
            common=common,
            interface={"name": "Gi0/0", "untagged_vlan": 100},
            device_location_id="loc-uuid",
            warnings=[],
        )
        self.assertEqual(result, "vlan-uuid")
        common.ensure_vlan_exists.assert_awaited_once_with(100, location_id="loc-uuid")

    async def test_raw_vid_with_no_location(self) -> None:
        common = self._common()
        await _resolve_untagged_vlan_id(
            common=common,
            interface={"name": "Gi0/0", "untagged_vlan": 100},
            device_location_id=None,
            warnings=[],
        )
        common.ensure_vlan_exists.assert_awaited_once_with(100, location_id=None)

    async def test_invalid_value_warns_and_returns_none(self) -> None:
        common = self._common()
        warnings: list[str] = []
        result = await _resolve_untagged_vlan_id(
            common=common,
            interface={"name": "Gi0/0", "untagged_vlan": "not-a-vid-or-uuid"},
            device_location_id=None,
            warnings=warnings,
        )
        self.assertIsNone(result)
        self.assertEqual(len(warnings), 1)
        self.assertIn("Gi0/0", warnings[0])
        common.ensure_vlan_exists.assert_not_awaited()


class ResolveTaggedVlanIdsTests(unittest.IsolatedAsyncioTestCase):
    def _common(self) -> MagicMock:
        common = MagicMock()
        common.ensure_vlan_exists = AsyncMock(return_value="vlan-uuid")
        return common

    async def test_missing_returns_empty_list(self) -> None:
        common = self._common()
        result = await _resolve_tagged_vlan_ids(
            common=common, interface={"name": "Gi0/0"}, device_location_id=None, warnings=[]
        )
        self.assertEqual(result, [])
        common.ensure_vlan_exists.assert_not_awaited()

    async def test_raw_vids_resolved_via_ensure_vlan_exists(self) -> None:
        common = self._common()
        result = await _resolve_tagged_vlan_ids(
            common=common,
            interface={"name": "Gi0/0", "tagged_vlans": [10, 20]},
            device_location_id="loc-uuid",
            warnings=[],
        )
        self.assertEqual(result, ["vlan-uuid", "vlan-uuid"])
        common.ensure_vlan_exists.assert_any_await(10, location_id="loc-uuid")
        common.ensure_vlan_exists.assert_any_await(20, location_id="loc-uuid")

    async def test_already_uuid_passes_through_without_resolving(self) -> None:
        common = self._common()
        result = await _resolve_tagged_vlan_ids(
            common=common,
            interface={
                "name": "Gi0/0",
                "tagged_vlans": ["3542814a-d33f-4cc3-bfdd-eb3a35945b31"],
            },
            device_location_id=None,
            warnings=[],
        )
        self.assertEqual(result, ["3542814a-d33f-4cc3-bfdd-eb3a35945b31"])
        common.ensure_vlan_exists.assert_not_awaited()

    async def test_invalid_entry_warns_and_is_skipped(self) -> None:
        common = self._common()
        warnings: list[str] = []
        result = await _resolve_tagged_vlan_ids(
            common=common,
            interface={"name": "Gi0/0", "tagged_vlans": [10, "not-a-vid-or-uuid"]},
            device_location_id=None,
            warnings=warnings,
        )
        self.assertEqual(result, ["vlan-uuid"])
        self.assertEqual(len(warnings), 1)
        self.assertIn("Gi0/0", warnings[0])

    def test_state_to_result_counts(self) -> None:
        state = _InterfaceUpdateState()
        state.created_interfaces = ["a", "b"]
        state.updated_interfaces = ["c"]
        state.failed_interfaces = ["d"]
        state.ip_address_map = {"a:1": "ip1"}
        state.primary_ipv4_id = "ip1"
        state.interfaces_deleted = 3
        result = state.to_result()
        self.assertEqual(result.interfaces_created, 2)
        self.assertEqual(result.interfaces_updated, 1)
        self.assertEqual(result.interfaces_failed, 1)
        self.assertEqual(result.interfaces_deleted, 3)
        self.assertEqual(result.ip_addresses_created, 1)
        self.assertEqual(result.primary_ip4_id, "ip1")


def _make_service(rest_dispatch=None) -> InterfaceManagerService:
    svc = InterfaceManagerService(MagicMock())
    svc.nautobot = MagicMock()
    if rest_dispatch is not None:
        svc.nautobot.rest_request = AsyncMock(side_effect=rest_dispatch)
    else:
        svc.nautobot.rest_request = AsyncMock(return_value={})
    common = MagicMock()
    common.resolve_namespace_id = AsyncMock(return_value="ns-uuid")
    common.ensure_ip_address_exists = AsyncMock(return_value="ip-uuid")
    common.resolve_status_id = AsyncMock(return_value="status-uuid")
    common.resolve_interface_by_name = AsyncMock(return_value=None)
    common.resolve_role_id_for_content_type = AsyncMock(return_value="role-uuid")
    common.ensure_vlan_exists = AsyncMock(return_value="vlan-uuid")
    svc.common = common
    return svc


class EnsureOneInterfaceIpTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_map_entry_on_success(self) -> None:
        svc = _make_service()
        entry = await svc._ensure_one_interface_ip(
            interface={"name": "Gi0/0", "status": "active"},
            ip_data={"address": "10.0.0.1/24", "namespace": "Global", "ip_role": "Secondary"},
            warnings=[],
            add_prefixes_automatically=False,
        )
        self.assertEqual(entry, ("Gi0/0:10.0.0.1/24", "ip-uuid"))
        svc.common.resolve_role_id_for_content_type.assert_awaited_once_with(
            "Secondary", "ipam.ipaddress"
        )
        _args, kwargs = svc.common.ensure_ip_address_exists.call_args
        self.assertEqual(kwargs["role"], "role-uuid")

    async def test_unresolved_role_warns_and_omits_role(self) -> None:
        svc = _make_service()
        svc.common.resolve_role_id_for_content_type = AsyncMock(return_value=None)
        warnings: list[str] = []
        entry = await svc._ensure_one_interface_ip(
            interface={"name": "Gi0/0", "status": "active"},
            ip_data={"address": "10.0.0.1/24", "namespace": "Global", "ip_role": "Bogus"},
            warnings=warnings,
            add_prefixes_automatically=False,
        )
        self.assertEqual(entry, ("Gi0/0:10.0.0.1/24", "ip-uuid"))
        self.assertEqual(len(warnings), 1)
        self.assertIn("Bogus", warnings[0])
        _args, kwargs = svc.common.ensure_ip_address_exists.call_args
        self.assertNotIn("role", kwargs)

    async def test_missing_address_returns_none(self) -> None:
        svc = _make_service()
        result = await svc._ensure_one_interface_ip(
            interface={"name": "Gi0/0"}, ip_data={}, warnings=[], add_prefixes_automatically=False
        )
        self.assertIsNone(result)

    async def test_error_appends_warning_and_returns_none(self) -> None:
        svc = _make_service()
        svc.common.ensure_ip_address_exists = AsyncMock(side_effect=RuntimeError("kaboom"))
        warnings: list[str] = []
        result = await svc._ensure_one_interface_ip(
            interface={"name": "Gi0/0"},
            ip_data={"address": "10.0.0.1/24", "namespace": "Global"},
            warnings=warnings,
            add_prefixes_automatically=False,
        )
        self.assertIsNone(result)
        self.assertEqual(len(warnings), 1)

    async def test_missing_prefix_error_reraises_when_no_autocreate(self) -> None:
        svc = _make_service()
        svc.common.ensure_ip_address_exists = AsyncMock(
            side_effect=RuntimeError("No suitable parent prefix found")
        )
        with self.assertRaises(RuntimeError):
            await svc._ensure_one_interface_ip(
                interface={"name": "Gi0/0"},
                ip_data={"address": "10.0.0.1/24", "namespace": "Global"},
                warnings=[],
                add_prefixes_automatically=False,
            )


class CreateIpAddressesTests(unittest.IsolatedAsyncioTestCase):
    async def test_builds_map_across_interfaces(self) -> None:
        svc = _make_service()
        interfaces = [
            {"name": "Gi0/0", "ip_addresses": [{"address": "10.0.0.1/24", "namespace": "Global"}]},
            {"name": "Gi0/1"},  # no IPs -> skipped
        ]
        result = await svc._create_ip_addresses(interfaces, warnings=[])
        self.assertEqual(result, {"Gi0/0:10.0.0.1/24": "ip-uuid"})


class CreateOrUpdateInterfaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_type_returns_none(self) -> None:
        svc = _make_service()
        result = await svc._create_or_update_interface("d1", {"name": "x", "type": ""}, [])
        self.assertEqual(result, (None, False))

    async def test_creates_new_interface(self) -> None:
        svc = _make_service(rest_dispatch=lambda **kw: {"id": "if-new"})
        result = await svc._create_or_update_interface(
            "d1", {"name": "Gi0/0", "type": "virtual"}, []
        )
        self.assertEqual(result, ("if-new", False))

    async def test_patches_existing_interface(self) -> None:
        svc = _make_service(rest_dispatch=lambda **kw: {})
        svc.common.resolve_interface_by_name = AsyncMock(return_value="if-existing")
        result = await svc._create_or_update_interface(
            "d1", {"name": "Gi0/0", "type": "virtual"}, []
        )
        self.assertEqual(result, ("if-existing", True))

    async def test_patch_existing_interface_error_still_returns_updated(self) -> None:
        svc = _make_service()
        svc.nautobot.rest_request = AsyncMock(side_effect=RuntimeError("patch failed"))
        warnings: list[str] = []
        result = await svc._patch_existing_interface(
            "if1", {"name": "Gi0/0"}, {"name": "Gi0/0", "device": "d1", "type": "virtual"}, warnings
        )
        self.assertEqual(result, ("if1", True))
        self.assertEqual(len(warnings), 1)

    async def test_create_race_fallback_patches_on_unique_error(self) -> None:
        svc = _make_service()
        svc.nautobot.rest_request = AsyncMock(
            side_effect=[RuntimeError("fields must make a unique set"), {}]
        )
        svc.common.resolve_interface_by_name = AsyncMock(return_value="if-raced")
        result = await svc._create_interface_with_race_fallback(
            device_id="d1",
            interface={"name": "Gi0/0"},
            interface_payload={"name": "Gi0/0", "device": "d1", "type": "virtual"},
            warnings=[],
        )
        self.assertEqual(result, ("if-raced", True))

    async def test_untagged_vlan_vid_resolved_with_device_location(self) -> None:
        svc = _make_service(rest_dispatch=lambda **kw: {"id": "if-new"})
        await svc._create_or_update_interface(
            "d1",
            {"name": "Gi0/0", "type": "virtual", "untagged_vlan": 100},
            [],
            device_location_id="loc-uuid",
        )
        svc.common.ensure_vlan_exists.assert_awaited_once_with(100, location_id="loc-uuid")

    async def test_create_race_fallback_generic_error_warns(self) -> None:
        svc = _make_service()
        svc.nautobot.rest_request = AsyncMock(side_effect=RuntimeError("500 server error"))
        warnings: list[str] = []
        result = await svc._create_interface_with_race_fallback(
            device_id="d1",
            interface={"name": "Gi0/0"},
            interface_payload={"name": "Gi0/0", "device": "d1", "type": "virtual"},
            warnings=warnings,
        )
        self.assertEqual(result, (None, False))
        self.assertEqual(len(warnings), 1)


class CleanInterfaceIpsTests(unittest.IsolatedAsyncioTestCase):
    async def test_deletes_existing_assignments(self) -> None:
        calls: list[tuple] = []

        async def dispatch(**kw):
            calls.append((kw.get("method"), kw.get("endpoint")))
            if kw.get("method") == "GET":
                return {"count": 1, "results": [{"id": "assoc1"}]}
            return {}

        svc = _make_service(rest_dispatch=dispatch)
        await svc._clean_interface_ips("if1", "Gi0/0", [])
        self.assertTrue(any(m == "DELETE" for m, _ in calls))

    async def test_swallows_list_errors_into_warnings(self) -> None:
        svc = _make_service()
        svc.nautobot.rest_request = AsyncMock(side_effect=RuntimeError("boom"))
        warnings: list[str] = []
        await svc._clean_interface_ips("if1", "Gi0/0", warnings)
        self.assertEqual(len(warnings), 1)


class AssignIpToInterfaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_none_when_no_ip_field(self) -> None:
        svc = _make_service()
        result = await svc._assign_ip_to_interface({"name": "Gi0/0"}, "if1", {}, [])
        self.assertIsNone(result)

    async def test_returns_none_when_not_in_map(self) -> None:
        svc = _make_service()
        result = await svc._assign_ip_to_interface(
            {"name": "Gi0/0", "ip_address": "10.0.0.1/24"}, "if1", {}, []
        )
        self.assertIsNone(result)

    async def test_creates_assignment_when_absent(self) -> None:
        async def dispatch(**kw):
            if kw.get("method") == "GET":
                return {"count": 0}
            return {"id": "assoc"}

        svc = _make_service(rest_dispatch=dispatch)
        result = await svc._assign_ip_to_interface(
            {"name": "Gi0/0", "ip_address": "10.0.0.1/24"},
            "if1",
            {"Gi0/0:10.0.0.1/24": "ip1"},
            [],
        )
        self.assertEqual(result, "ip1")

    async def test_skips_create_when_assignment_exists(self) -> None:
        svc = _make_service(rest_dispatch=lambda **kw: {"count": 1})
        result = await svc._assign_ip_to_interface(
            {"name": "Gi0/0", "ip_address": "10.0.0.1/24"},
            "if1",
            {"Gi0/0:10.0.0.1/24": "ip1"},
            [],
        )
        self.assertEqual(result, "ip1")

    async def test_exception_appends_warning(self) -> None:
        svc = _make_service()
        svc.nautobot.rest_request = AsyncMock(side_effect=RuntimeError("boom"))
        warnings: list[str] = []
        result = await svc._assign_ip_to_interface(
            {"name": "Gi0/0", "ip_address": "10.0.0.1/24"},
            "if1",
            {"Gi0/0:10.0.0.1/24": "ip1"},
            warnings,
        )
        self.assertIsNone(result)
        self.assertEqual(len(warnings), 1)


class SetPrimaryAndOrphanTests(unittest.IsolatedAsyncioTestCase):
    async def test_set_primary_ipv4_success(self) -> None:
        svc = _make_service(rest_dispatch=lambda **kw: {})
        await svc._set_primary_ipv4("d1", "ip1", [])

    async def test_set_primary_ipv4_error_warns(self) -> None:
        svc = _make_service()
        svc.nautobot.rest_request = AsyncMock(side_effect=RuntimeError("boom"))
        warnings: list[str] = []
        await svc._set_primary_ipv4("d1", "ip1", warnings)
        self.assertEqual(len(warnings), 1)

    async def test_delete_orphan_interfaces(self) -> None:
        async def dispatch(**kw):
            if kw.get("method") == "GET" and "device_id" in kw.get("endpoint", ""):
                return {
                    "results": [
                        {"id": "keep", "name": "Gi0/0"},
                        {"id": "drop", "name": "Gi9/9"},
                    ]
                }
            return {"count": 0}

        svc = _make_service(rest_dispatch=dispatch)
        deleted = await svc._delete_orphan_device_interfaces("d1", {"Gi0/0"}, [])
        self.assertEqual(deleted, 1)

    async def test_delete_orphan_interfaces_list_failure(self) -> None:
        svc = _make_service()
        svc.nautobot.rest_request = AsyncMock(side_effect=RuntimeError("boom"))
        warnings: list[str] = []
        deleted = await svc._delete_orphan_device_interfaces("d1", set(), warnings)
        self.assertEqual(deleted, 0)
        self.assertEqual(len(warnings), 1)


class UpdateDeviceInterfacesTests(unittest.IsolatedAsyncioTestCase):
    async def test_happy_path_creates_interface_and_sets_primary(self) -> None:
        async def dispatch(**kw):
            method, endpoint = kw.get("method"), kw.get("endpoint", "")
            if method == "POST" and endpoint == "dcim/interfaces/":
                return {"id": "if1"}
            if method == "GET" and "ip-address-to-interface" in endpoint:
                return {"count": 0}
            if method == "POST" and "ip-address-to-interface" in endpoint:
                return {"id": "assoc"}
            return {}

        svc = _make_service(rest_dispatch=dispatch)
        interfaces = [
            {
                "name": "Gi0/0",
                "type": "1000base-t",
                "status": "active",
                "ip_addresses": [
                    {"address": "10.0.0.1/24", "namespace": "Global", "is_primary": True}
                ],
            }
        ]
        result = await svc.update_device_interfaces("d1", interfaces)
        self.assertEqual(result.interfaces_created, 1)
        self.assertEqual(result.ip_addresses_created, 1)
        self.assertEqual(result.primary_ip4_id, "ip-uuid")

    async def test_process_one_interface_records_failure(self) -> None:
        svc = _make_service()
        state = _InterfaceUpdateState()
        svc._create_or_update_interface = AsyncMock(side_effect=RuntimeError("boom"))
        await svc._process_one_interface(
            device_id="d1", interface={"name": "Gi0/0"}, state=state
        )
        self.assertEqual(state.failed_interfaces, ["Gi0/0"])
        self.assertEqual(len(state.warnings), 1)

    async def test_process_one_interface_records_interface_id_map(self) -> None:
        svc = _make_service()
        state = _InterfaceUpdateState()
        svc._create_or_update_interface = AsyncMock(return_value=("if1", False))
        await svc._process_one_interface(
            device_id="d1", interface={"name": "Gi0/0"}, state=state
        )
        self.assertEqual(state.interface_id_map, {"Gi0/0": "if1"})

    async def test_two_interface_batch_sets_lag_membership(self) -> None:
        created_ids = {"Port-channel10": "pc-id", "Ethernet0/2": "eth-id"}
        patch_calls: list[tuple] = []

        async def dispatch(**kw):
            method, endpoint = kw.get("method"), kw.get("endpoint", "")
            if method == "POST" and endpoint == "dcim/interfaces/":
                name = kw.get("data", {}).get("name")
                return {"id": created_ids[name]}
            if method == "PATCH" and endpoint.startswith("dcim/interfaces/"):
                patch_calls.append((endpoint, kw.get("data")))
                return {}
            if method == "GET" and "ip-address-to-interface" in endpoint:
                return {"count": 0}
            return {}

        svc = _make_service(rest_dispatch=dispatch)
        interfaces = [
            {"name": "Ethernet0/2", "type": "100base-tx", "lag": "Port-channel10"},
            {"name": "Port-channel10", "type": "lag"},
        ]
        result = await svc.update_device_interfaces("d1", interfaces)
        self.assertEqual(result.interfaces_created, 2)
        self.assertIn(("dcim/interfaces/eth-id/", {"lag": {"id": "pc-id"}}), patch_calls)


class AssignLagMembershipsTests(unittest.IsolatedAsyncioTestCase):
    async def test_lag_in_same_batch_resolved_from_map(self) -> None:
        svc = _make_service(rest_dispatch=lambda **kw: {})
        state = _InterfaceUpdateState()
        state.interface_id_map = {"Ethernet0/2": "eth-id", "Port-channel10": "pc-id"}
        await svc._assign_lag_memberships(
            device_id="d1",
            interfaces=[{"name": "Ethernet0/2", "lag": "Port-channel10"}],
            state=state,
        )
        svc.common.resolve_interface_by_name.assert_not_awaited()
        svc.nautobot.rest_request.assert_awaited_once_with(
            endpoint="dcim/interfaces/eth-id/",
            method="PATCH",
            data={"lag": {"id": "pc-id"}},
        )

    async def test_lag_not_in_batch_falls_back_to_resolver(self) -> None:
        svc = _make_service(rest_dispatch=lambda **kw: {})
        svc.common.resolve_interface_by_name = AsyncMock(return_value="pc-existing")
        state = _InterfaceUpdateState()
        state.interface_id_map = {"Ethernet0/2": "eth-id"}
        await svc._assign_lag_memberships(
            device_id="d1",
            interfaces=[{"name": "Ethernet0/2", "lag": "Port-channel10"}],
            state=state,
        )
        svc.common.resolve_interface_by_name.assert_awaited_once_with(
            device_id="d1", interface_name="Port-channel10"
        )
        svc.nautobot.rest_request.assert_awaited_once_with(
            endpoint="dcim/interfaces/eth-id/",
            method="PATCH",
            data={"lag": {"id": "pc-existing"}},
        )

    async def test_lag_already_uuid_used_directly(self) -> None:
        svc = _make_service(rest_dispatch=lambda **kw: {})
        state = _InterfaceUpdateState()
        state.interface_id_map = {"Ethernet0/2": "eth-id"}
        await svc._assign_lag_memberships(
            device_id="d1",
            interfaces=[
                {"name": "Ethernet0/2", "lag": "3542814a-d33f-4cc3-bfdd-eb3a35945b31"}
            ],
            state=state,
        )
        svc.common.resolve_interface_by_name.assert_not_awaited()
        svc.nautobot.rest_request.assert_awaited_once_with(
            endpoint="dcim/interfaces/eth-id/",
            method="PATCH",
            data={"lag": {"id": "3542814a-d33f-4cc3-bfdd-eb3a35945b31"}},
        )

    async def test_lag_not_found_warns_and_skips(self) -> None:
        svc = _make_service()
        svc.common.resolve_interface_by_name = AsyncMock(return_value=None)
        state = _InterfaceUpdateState()
        state.interface_id_map = {"Ethernet0/2": "eth-id"}
        await svc._assign_lag_memberships(
            device_id="d1",
            interfaces=[{"name": "Ethernet0/2", "lag": "Port-channel10"}],
            state=state,
        )
        svc.nautobot.rest_request.assert_not_awaited()
        self.assertEqual(len(state.warnings), 1)
        self.assertIn("Port-channel10", state.warnings[0])

    async def test_lag_self_reference_warns_and_skips(self) -> None:
        svc = _make_service()
        state = _InterfaceUpdateState()
        state.interface_id_map = {"Ethernet0/2": "eth-id"}
        await svc._assign_lag_memberships(
            device_id="d1",
            interfaces=[{"name": "Ethernet0/2", "lag": "Ethernet0/2"}],
            state=state,
        )
        svc.nautobot.rest_request.assert_not_awaited()
        self.assertEqual(len(state.warnings), 1)

    async def test_member_missing_from_id_map_skipped(self) -> None:
        svc = _make_service()
        state = _InterfaceUpdateState()
        state.interface_id_map = {}
        await svc._assign_lag_memberships(
            device_id="d1",
            interfaces=[{"name": "Ethernet0/2", "lag": "Port-channel10"}],
            state=state,
        )
        svc.common.resolve_interface_by_name.assert_not_awaited()
        svc.nautobot.rest_request.assert_not_awaited()
        self.assertEqual(state.warnings, [])

    async def test_no_lag_field_skipped(self) -> None:
        svc = _make_service()
        state = _InterfaceUpdateState()
        state.interface_id_map = {"Ethernet0/2": "eth-id"}
        await svc._assign_lag_memberships(
            device_id="d1",
            interfaces=[{"name": "Ethernet0/2"}],
            state=state,
        )
        svc.nautobot.rest_request.assert_not_awaited()

    async def test_patch_failure_appends_warning_without_raising(self) -> None:
        svc = _make_service()
        svc.nautobot.rest_request = AsyncMock(side_effect=RuntimeError("boom"))
        state = _InterfaceUpdateState()
        state.interface_id_map = {"Ethernet0/2": "eth-id", "Port-channel10": "pc-id"}
        await svc._assign_lag_memberships(
            device_id="d1",
            interfaces=[{"name": "Ethernet0/2", "lag": "Port-channel10"}],
            state=state,
        )
        self.assertEqual(len(state.warnings), 1)
        self.assertIn("Ethernet0/2", state.warnings[0])


if __name__ == "__main__":
    unittest.main()
