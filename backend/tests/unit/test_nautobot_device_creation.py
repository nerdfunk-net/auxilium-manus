"""Unit tests for services/nautobot/devices/creation.py (DeviceCreationService)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from services.nautobot.common.exceptions import NautobotAPIError
from services.nautobot.devices.creation import DeviceCreationService
from services.nautobot.devices.types import AddDeviceRequest

_UUID = "550e8400-e29b-41d4-a716-446655440000"


def _request(**overrides) -> AddDeviceRequest:
    base = dict(
        name="router1",
        role="leaf",
        status="active",
        location="dc1",
        device_type="C9300",
    )
    base.update(overrides)
    return AddDeviceRequest(**base)


def _service(rest_dispatch=None) -> DeviceCreationService:
    svc = DeviceCreationService(MagicMock())
    svc.nautobot = MagicMock()
    svc.nautobot.rest_request = AsyncMock(
        side_effect=rest_dispatch if rest_dispatch else (lambda *a, **k: {"id": "dev-1"})
    )
    common = MagicMock()
    common.resolve_device_type_id = AsyncMock(return_value="dt-uuid")
    common.resolve_role_id = AsyncMock(return_value="role-uuid")
    common.resolve_status_id = AsyncMock(return_value="status-uuid")
    common.resolve_location_id = AsyncMock(return_value="loc-uuid")
    common.resolve_platform_id = AsyncMock(return_value="plat-uuid")
    common.resolve_rack_id = AsyncMock(return_value="rack-uuid")
    svc.common = common
    svc.interface_manager = MagicMock()
    svc.interface_manager.update_device_interfaces = AsyncMock(
        return_value=SimpleNamespace(
            interfaces_created=1, interfaces_updated=0, interfaces_failed=0, warnings=[]
        )
    )
    return svc


class ExtractVcPositionTests(unittest.TestCase):
    def test_numeric_suffix(self) -> None:
        self.assertEqual(DeviceCreationService._extract_vc_position_from_name("lab-004:4"), 4)

    def test_no_colon(self) -> None:
        self.assertIsNone(DeviceCreationService._extract_vc_position_from_name("router1"))

    def test_non_numeric_suffix(self) -> None:
        self.assertIsNone(DeviceCreationService._extract_vc_position_from_name("router:abc"))


class ResolveNamesTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolves_all_named_fields(self) -> None:
        svc = _service()
        resolved = await svc._resolve_request_names_to_ids(_request())
        self.assertEqual(resolved.device_type, "dt-uuid")
        self.assertEqual(resolved.role, "role-uuid")
        self.assertEqual(resolved.status, "status-uuid")
        self.assertEqual(resolved.location, "loc-uuid")

    async def test_uuids_pass_through_untouched(self) -> None:
        svc = _service()
        req = _request(role=_UUID, status=_UUID, location=_UUID, device_type=_UUID)
        resolved = await svc._resolve_request_names_to_ids(req)
        self.assertIs(resolved, req)
        svc.common.resolve_role_id.assert_not_called()

    async def test_missing_device_type_raises(self) -> None:
        svc = _service()
        svc.common.resolve_device_type_id = AsyncMock(return_value=None)
        with self.assertRaises(ValueError):
            await svc._resolve_request_names_to_ids(_request())

    async def test_missing_role_raises(self) -> None:
        svc = _service()
        svc.common.resolve_role_id = AsyncMock(return_value=None)
        with self.assertRaises(ValueError):
            await svc._resolve_request_names_to_ids(_request())

    async def test_missing_location_raises(self) -> None:
        svc = _service()
        svc.common.resolve_location_id = AsyncMock(return_value=None)
        with self.assertRaises(ValueError):
            await svc._resolve_request_names_to_ids(_request())

    async def test_missing_platform_is_warning_not_error(self) -> None:
        svc = _service()
        svc.common.resolve_platform_id = AsyncMock(return_value=None)
        resolved = await svc._resolve_request_names_to_ids(_request(platform="ios"))
        self.assertIsNone(resolved.platform)


class ValidateDryRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_reports_existing_device_and_missing_refs(self) -> None:
        async def dispatch(endpoint, *a, **k):
            if endpoint.startswith("dcim/devices/?name="):
                return {"count": 1}
            return {"count": 0}

        svc = _service(rest_dispatch=dispatch)
        req = _request(role=_UUID, status=_UUID, location=_UUID, device_type=_UUID)
        result = await svc._validate_dry_run(req)
        self.assertFalse(result["success"])
        self.assertTrue(any("already exists" in e for e in result["errors"]))
        self.assertTrue(any("Device type" in e for e in result["errors"]))

    async def test_success_when_everything_resolves(self) -> None:
        async def dispatch(endpoint, *a, **k):
            if endpoint.startswith("dcim/devices/?name="):
                return {"count": 0}
            return {"count": 1}

        svc = _service(rest_dispatch=dispatch)
        req = _request(
            role=_UUID, status=_UUID, location=_UUID, device_type=_UUID, platform=_UUID
        )
        result = await svc._validate_dry_run(req)
        self.assertTrue(result["success"])
        self.assertEqual(result["errors"], [])


class CreateDeviceLowLevelTests(unittest.IsolatedAsyncioTestCase):
    async def test_builds_payload_with_optional_fields_and_rack(self) -> None:
        captured: dict = {}

        async def dispatch(*a, **k):
            captured.update(k)
            return {"id": "dev-1"}

        svc = _service(rest_dispatch=dispatch)
        req = _request(
            role=_UUID,
            status=_UUID,
            location=_UUID,
            device_type=_UUID,
            serial="SN1",
            tags=["lab"],
            custom_fields={"site": "NYC"},
            rack="A1",
            face="Front",
            position=10,
        )
        device_id, _resp = await svc._create_device(req)
        self.assertEqual(device_id, "dev-1")
        payload = captured["data"]
        self.assertEqual(payload["serial"], "SN1")
        self.assertEqual(payload["rack"], "rack-uuid")
        self.assertEqual(payload["face"], "front")
        self.assertEqual(payload["position"], 10)

    async def test_rack_not_found_is_skipped(self) -> None:
        captured: dict = {}

        async def dispatch(*a, **k):
            captured.update(k)
            return {"id": "dev-1"}

        svc = _service(rest_dispatch=dispatch)
        svc.common.resolve_rack_id = AsyncMock(return_value=None)
        req = _request(role=_UUID, status=_UUID, location=_UUID, device_type=_UUID, rack="ghost")
        await svc._create_device(req)
        self.assertNotIn("rack", captured["data"])

    async def test_missing_id_in_response_raises(self) -> None:
        svc = _service(rest_dispatch=lambda *a, **k: {})
        req = _request(role=_UUID, status=_UUID, location=_UUID, device_type=_UUID)
        with self.assertRaises(NautobotAPIError):
            await svc._create_device(req)


class VirtualChassisTests(unittest.IsolatedAsyncioTestCase):
    async def test_join_uses_name_position(self) -> None:
        calls: list = []

        async def dispatch(endpoint, *a, **k):
            calls.append((endpoint, k.get("data")))
            return {}

        svc = _service(rest_dispatch=dispatch)
        await svc._join_virtual_chassis("dev-1", "vc-1", "lab:5", [])
        patch_call = next(c for c in calls if c[0] == "dcim/devices/dev-1/")
        self.assertEqual(patch_call[1]["vc_position"], 5)

    async def test_join_falls_back_to_max_position_plus_one(self) -> None:
        async def dispatch(endpoint, *a, **k):
            if endpoint.startswith("dcim/devices/?virtual_chassis="):
                return {"results": [{"vc_position": 1}, {"vc_position": 3}]}
            return {}

        svc = _service(rest_dispatch=dispatch)
        warnings: list[str] = []
        await svc._join_virtual_chassis("dev-1", "vc-1", "router1", warnings)
        self.assertEqual(warnings, [])

    async def test_join_error_appends_warning(self) -> None:
        svc = _service(rest_dispatch=AsyncMock(side_effect=RuntimeError("boom")))
        warnings: list[str] = []
        await svc._join_virtual_chassis("dev-1", "vc-1", "router1", warnings)
        self.assertEqual(len(warnings), 1)

    async def test_create_and_join_success(self) -> None:
        async def dispatch(endpoint, *a, **k):
            if endpoint == "dcim/virtual-chassis/":
                return {"id": "vc-new"}
            return {}

        svc = _service(rest_dispatch=dispatch)
        warnings: list[str] = []
        await svc._create_and_join_virtual_chassis("dev-1", "VC1", warnings)
        self.assertEqual(warnings, [])

    async def test_create_and_join_error_appends_warning(self) -> None:
        svc = _service(rest_dispatch=AsyncMock(side_effect=RuntimeError("boom")))
        warnings: list[str] = []
        await svc._create_and_join_virtual_chassis("dev-1", "VC1", warnings)
        self.assertEqual(len(warnings), 1)


class CreateDeviceOrchestrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_dry_run_returns_validation_result(self) -> None:
        svc = _service(rest_dispatch=lambda *a, **k: {"count": 0})
        req = _request(role=_UUID, status=_UUID, location=_UUID, device_type=_UUID, dry_run=True)
        result = await svc.create_device(req)
        self.assertTrue(result["dry_run"])

    async def test_full_create_with_interfaces_and_new_vc(self) -> None:
        async def dispatch(endpoint, *a, **k):
            if endpoint == "dcim/virtual-chassis/":
                return {"id": "vc-new"}
            return {"id": "dev-1"}

        svc = _service(rest_dispatch=dispatch)
        req = _request(
            role=_UUID,
            status=_UUID,
            location=_UUID,
            device_type=_UUID,
            new_virtual_chassis_name="VC1",
            interfaces=[{"name": "Gi0/0", "type": "virtual"}],
        )
        result = await svc.create_device(req)
        self.assertTrue(result["success"])
        self.assertEqual(result["interfaces_created"], 1)
        svc.interface_manager.update_device_interfaces.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
