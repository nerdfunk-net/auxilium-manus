"""Unit tests for services/nautobot/devices/update.py (DeviceUpdateService)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from services.nautobot.devices.update import (
    DeviceUpdateService,
    _default_primary_ip_interface_config,
    _enforce_rack_position_face,
    _prepare_update_field,
    _verify_primary_ip4_applied,
)

_UUID = "550e8400-e29b-41d4-a716-446655440000"


class PrepareUpdateFieldTests(unittest.TestCase):
    def test_none_value_dropped_for_non_rack_field(self) -> None:
        self.assertIsNone(_prepare_update_field("serial", None))

    def test_none_value_kept_for_rack_clearable_field(self) -> None:
        self.assertEqual(_prepare_update_field("rack", None), ("rack", None))

    def test_blank_string_dropped(self) -> None:
        self.assertIsNone(_prepare_update_field("serial", "   "))

    def test_dotted_field_flattened_and_value_stripped(self) -> None:
        self.assertEqual(_prepare_update_field("platform.name", "  ios  "), ("platform", "ios"))


class EnforceRackPositionFaceTests(unittest.TestCase):
    def test_position_without_face_is_dropped(self) -> None:
        data = {"position": 10}
        _enforce_rack_position_face(data)
        self.assertNotIn("position", data)

    def test_position_with_face_is_kept(self) -> None:
        data = {"position": 10, "face": "front"}
        _enforce_rack_position_face(data)
        self.assertEqual(data["position"], 10)


class VerifyPrimaryIp4Tests(unittest.TestCase):
    def test_matches_dict_form(self) -> None:
        _verify_primary_ip4_applied(
            device_id="d1", expected_ip_id="ip1", result={"primary_ip4": {"id": "ip1"}}
        )

    def test_matches_string_form(self) -> None:
        _verify_primary_ip4_applied(
            device_id="d1", expected_ip_id="ip1", result={"primary_ip4": "ip1"}
        )

    def test_mismatch_raises(self) -> None:
        with self.assertRaises(ValueError):
            _verify_primary_ip4_applied(
                device_id="d1", expected_ip_id="ip1", result={"primary_ip4": "other"}
            )

    def test_default_primary_ip_interface_config_shape(self) -> None:
        cfg = _default_primary_ip_interface_config()
        self.assertEqual(cfg["name"], "Loopback")
        self.assertFalse(cfg["mgmt_interface_create_on_ip_change"])


def _service() -> DeviceUpdateService:
    svc = DeviceUpdateService(MagicMock())
    svc.nautobot = MagicMock()
    svc.nautobot.rest_request = AsyncMock(return_value={})
    common = MagicMock()
    common._is_valid_uuid = lambda v: bool(v) and len(str(v)) == 36 and str(v).count("-") == 4
    common.resolve_status_id = AsyncMock(return_value="status-uuid")
    common.resolve_platform_id = AsyncMock(return_value="plat-uuid")
    common.resolve_role_id = AsyncMock(return_value="role-uuid")
    common.resolve_location_id = AsyncMock(return_value="loc-uuid")
    common.resolve_device_type_id = AsyncMock(return_value="dt-uuid")
    common.resolve_rack_id = AsyncMock(return_value="rack-uuid")
    common.resolve_device_id = AsyncMock(return_value="dev-1")
    common.normalize_tags = lambda v: v if isinstance(v, list) else str(v).split(",")
    common.get_device_details = AsyncMock(return_value={"name": "r1"})
    common.extract_primary_ip_address = AsyncMock(return_value=None)
    common.verify_device_updates = AsyncMock(return_value=(True, []))
    common.ensure_interface_with_ip = AsyncMock(return_value="ip-new")
    common.update_interface_ip = AsyncMock(return_value="ip-upd")
    svc.common = common
    svc.interface_manager = MagicMock()
    return svc


class ResultShapeHelperTests(unittest.TestCase):
    def test_empty_update_result(self) -> None:
        result = _service()._empty_update_result(
            device_id="d1", device_name="r1", details={"before": None}
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["updated_fields"], [])

    def test_compute_field_changes(self) -> None:
        changes = _service()._compute_field_changes(
            {"serial": "OLD"}, {"serial": "NEW"}, ["serial"]
        )
        self.assertEqual(changes, {"serial": {"from": "OLD", "to": "NEW"}})

    def test_success_message_includes_interface_counts(self) -> None:
        result = _service()._success_update_result(
            device_id="d1",
            device_name="r1",
            updated_fields=["serial"],
            warnings=[],
            interfaces_created=2,
            interfaces_updated=1,
            interfaces_failed=0,
            details={},
        )
        self.assertIn("2 interface(s) created", result["message"])


class ResolveDeviceIdTests(unittest.IsolatedAsyncioTestCase):
    async def test_requires_an_identifier(self) -> None:
        with self.assertRaises(ValueError):
            await _service()._resolve_device_id({})

    async def test_returns_id_and_given_name(self) -> None:
        svc = _service()
        self.assertEqual(
            await svc._resolve_device_id({"name": "r1"}), ("dev-1", "r1")
        )

    async def test_fetches_name_when_absent(self) -> None:
        svc = _service()
        svc.nautobot.rest_request = AsyncMock(return_value={"name": "fetched"})
        self.assertEqual(
            await svc._resolve_device_id({"ip_address": "10.0.0.1"}), ("dev-1", "fetched")
        )

    async def test_returns_none_tuple_when_unresolved(self) -> None:
        svc = _service()
        svc.common.resolve_device_id = AsyncMock(return_value=None)
        self.assertEqual(await svc._resolve_device_id({"name": "ghost"}), (None, None))

    async def test_resolve_for_update_raises_when_not_found(self) -> None:
        svc = _service()
        svc.common.resolve_device_id = AsyncMock(return_value=None)
        with self.assertRaises(ValueError):
            await svc._resolve_device_for_update({"name": "ghost"}, matching_strategy="exact")


class ResolveUpdateFieldTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_name_resolved(self) -> None:
        out = await _service()._resolve_update_field("status", "active", rack_location=None)
        self.assertEqual(out, ("set", "status", "status-uuid"))

    async def test_status_uuid_passthrough(self) -> None:
        out = await _service()._resolve_update_field("status", _UUID, rack_location=None)
        self.assertEqual(out, ("set", "status", _UUID))

    async def test_named_id_field_not_found_omits(self) -> None:
        svc = _service()
        svc.common.resolve_role_id = AsyncMock(return_value=None)
        out = await svc._resolve_update_field("role", "ghost", rack_location=None)
        self.assertEqual(out, ("omit",))

    async def test_rack_none_sets_null(self) -> None:
        out = await _service()._resolve_update_field("rack", None, rack_location=None)
        self.assertEqual(out, ("set", "rack", None))

    async def test_rack_name_not_found_omits(self) -> None:
        svc = _service()
        svc.common.resolve_rack_id = AsyncMock(return_value=None)
        out = await svc._resolve_update_field("rack", "ghost", rack_location="dc1")
        self.assertEqual(out, ("omit",))

    async def test_tags_normalized(self) -> None:
        out = await _service()._resolve_update_field("tags", "a,b", rack_location=None)
        self.assertEqual(out, ("set", "tags", ["a", "b"]))

    async def test_ip_namespace_becomes_namespace_outcome(self) -> None:
        out = await _service()._resolve_update_field("ip_namespace", "Mgmt", rack_location=None)
        self.assertEqual(out, ("namespace", "Mgmt"))

    async def test_custom_fields_non_dict_omitted(self) -> None:
        out = await _service()._resolve_update_field("custom_fields", "bad", rack_location=None)
        self.assertEqual(out, ("omit",))

    async def test_plain_field_set_verbatim(self) -> None:
        out = await _service()._resolve_update_field("serial", "SN1", rack_location=None)
        self.assertEqual(out, ("set", "serial", "SN1"))


class ValidateUpdateDataTests(unittest.IsolatedAsyncioTestCase):
    async def test_collects_validated_fields_and_namespace(self) -> None:
        svc = _service()
        validated, namespace = await svc.validate_update_data(
            "dev-1",
            {"serial": "SN1", "status": "active", "ip_namespace": "Mgmt", "empty": ""},
        )
        self.assertEqual(validated["serial"], "SN1")
        self.assertEqual(validated["status"], "status-uuid")
        self.assertEqual(namespace, "Mgmt")

    async def test_rack_position_without_face_dropped(self) -> None:
        svc = _service()
        validated, _ = await svc.validate_update_data("dev-1", {"position": 10})
        self.assertNotIn("position", validated)


class UpdateDevicePropertiesTests(unittest.IsolatedAsyncioTestCase):
    async def test_plain_fields_patched(self) -> None:
        svc = _service()
        fields = await svc._update_device_properties("dev-1", {"serial": "SN1"})
        self.assertEqual(fields, ["serial"])
        self.assertEqual(svc.nautobot.rest_request.await_args.kwargs["method"], "PATCH")

    async def test_primary_ip4_resolved_and_verified(self) -> None:
        svc = _service()
        svc.nautobot.rest_request = AsyncMock(return_value={"primary_ip4": {"id": "ip-new"}})
        fields = await svc._update_device_properties(
            "dev-1",
            {"primary_ip4": "10.0.0.1/24"},
            interface_config={"mgmt_interface_create_on_ip_change": True},
            ip_namespace="Global",
        )
        self.assertIn("primary_ip4", fields)
        svc.common.ensure_interface_with_ip.assert_awaited_once()

    async def test_primary_ip4_update_existing_interface_path(self) -> None:
        svc = _service()
        svc.nautobot.rest_request = AsyncMock(return_value={"primary_ip4": "ip-upd"})
        await svc._update_device_properties(
            "dev-1",
            {"primary_ip4": "10.0.0.1/24"},
            interface_config={"mgmt_interface_create_on_ip_change": False},
        )
        svc.common.update_interface_ip.assert_awaited_once()


class PropertyAndInterfaceUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def test_apply_property_updates_skips_when_empty(self) -> None:
        svc = _service()
        self.assertEqual(
            await svc._apply_property_updates(
                device_id="d1",
                device_name="r1",
                validated_data={},
                interface_config=None,
                ip_namespace=None,
                current_primary_ip4=None,
            ),
            [],
        )

    async def test_apply_interface_updates_extends_warnings(self) -> None:
        svc = _service()
        svc.interface_manager.update_device_interfaces = AsyncMock(
            return_value=MagicMock(
                interfaces_created=1,
                interfaces_updated=2,
                interfaces_failed=0,
                warnings=["w1"],
            )
        )
        warnings: list[str] = []
        created, updated, failed = await svc._apply_interface_updates(
            device_id="d1",
            interfaces=[{"name": "Gi0/0"}],
            add_prefix=True,
            sync_interfaces=False,
            warnings=warnings,
        )
        self.assertEqual((created, updated, failed), (1, 2, 0))
        self.assertEqual(warnings, ["w1"])

    async def test_collect_verification_warnings_on_mismatch(self) -> None:
        svc = _service()
        svc.common.verify_device_updates = AsyncMock(
            return_value=(False, [{"field": "serial", "expected": "A", "actual": "B"}])
        )
        warnings: list[str] = []
        await svc._collect_verification_warnings(
            device_id="d1", validated_data={}, after_state={}, warnings=warnings
        )
        self.assertEqual(len(warnings), 2)


class UpdateDeviceOrchestrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_fields_no_interfaces_returns_empty_result(self) -> None:
        svc = _service()
        result = await svc.update_device({"name": "r1"}, {})
        self.assertIn("no fields to update", result["message"].lower())

    async def test_happy_path_updates_field_and_finalizes(self) -> None:
        svc = _service()
        svc.common.get_device_details = AsyncMock(
            side_effect=[{"serial": "OLD"}, {"serial": "SN1"}]
        )
        result = await svc.update_device({"name": "r1"}, {"serial": "SN1"})
        self.assertTrue(result["success"])
        self.assertEqual(result["updated_fields"], ["serial"])
        self.assertEqual(result["details"]["changes"], {"serial": {"from": "OLD", "to": "SN1"}})


if __name__ == "__main__":
    unittest.main()
