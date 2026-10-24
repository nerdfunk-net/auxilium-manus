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
    common.resolve_secrets_group_id = AsyncMock(return_value="sg-uuid")
    common.resolve_rack_id = AsyncMock(return_value="rack-uuid")
    common.resolve_namespace_id = AsyncMock(return_value="ns-uuid")
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

    async def test_secrets_group_name_resolved_to_uuid(self) -> None:
        svc = _service()
        resolved = await svc._resolve_request_names_to_ids(_request(secrets_group="ssh-creds"))
        self.assertEqual(resolved.secrets_group, "sg-uuid")
        svc.common.resolve_secrets_group_id.assert_awaited_once_with("ssh-creds")

    async def test_secrets_group_uuid_passes_through(self) -> None:
        svc = _service()
        req = _request(
            role=_UUID, status=_UUID, location=_UUID, device_type=_UUID, secrets_group=_UUID
        )
        resolved = await svc._resolve_request_names_to_ids(req)
        self.assertEqual(resolved.secrets_group, _UUID)
        svc.common.resolve_secrets_group_id.assert_not_called()

    async def test_missing_secrets_group_raises(self) -> None:
        svc = _service()
        svc.common.resolve_secrets_group_id = AsyncMock(return_value=None)
        with self.assertRaises(ValueError):
            await svc._resolve_request_names_to_ids(_request(secrets_group="ghost"))


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

    async def test_reports_missing_secrets_group(self) -> None:
        async def dispatch(endpoint, *a, **k):
            if endpoint.startswith("extras/secrets-groups/"):
                return {"count": 0}
            return {"count": 0 if endpoint.startswith("dcim/devices/?name=") else 1}

        svc = _service(rest_dispatch=dispatch)
        req = _request(
            role=_UUID, status=_UUID, location=_UUID, device_type=_UUID, secrets_group=_UUID
        )
        result = await svc._validate_dry_run(req)
        self.assertFalse(result["success"])
        self.assertTrue(any("Secrets group" in e for e in result["errors"]))


def _iface(name: str = "eth0", *, type_: str | None = "1000base-t", ips=("10.0.0.1/24",), **extra):
    iface: dict = {"name": name, **extra}
    if type_ is not None:
        iface["type"] = type_
    if ips:
        iface["ip_addresses"] = [{"address": ip} for ip in ips]
    return iface


def _preflight_dispatch(*, prefix_count: int = 1, ip_count: int = 0):
    async def dispatch(endpoint, *a, **k):
        if endpoint.startswith("ipam/ip-addresses/?"):
            return {"count": ip_count}
        if endpoint.startswith("ipam/prefixes/?"):
            return {"count": prefix_count}
        return {"id": "dev-1", "count": 0}

    return dispatch


class PreflightTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_interfaces_give_no_errors(self) -> None:
        svc = _service(_preflight_dispatch())
        errors = await svc._preflight_checks(_request(interfaces=[_iface()], add_prefix=False))
        self.assertEqual(errors, [])

    async def test_interface_without_type_is_reported(self) -> None:
        svc = _service(_preflight_dispatch())
        errors = await svc._preflight_checks(_request(interfaces=[_iface(type_=None)]))
        self.assertEqual(len(errors), 1)
        self.assertIn("eth0", errors[0])
        self.assertIn("type is required", errors[0])

    async def test_blank_interface_type_is_reported(self) -> None:
        svc = _service(_preflight_dispatch())
        errors = await svc._preflight_checks(_request(interfaces=[_iface(type_="  ")]))
        self.assertTrue(any("type is required" in e for e in errors))

    async def test_unknown_namespace_is_reported(self) -> None:
        svc = _service(_preflight_dispatch())
        svc.common.resolve_namespace_id = AsyncMock(side_effect=ValueError("Namespace not found"))
        iface = _iface()
        iface["ip_addresses"] = [{"address": "10.0.0.1/24", "namespace": "black"}]
        errors = await svc._preflight_checks(_request(interfaces=[iface]))
        self.assertEqual(len(errors), 1)
        self.assertIn("Namespace 'black' not found", errors[0])

    async def test_blank_namespace_means_global(self) -> None:
        svc = _service(_preflight_dispatch())
        iface = _iface()
        iface["ip_addresses"] = [{"address": "10.0.0.1/24", "namespace": "  "}]
        errors = await svc._preflight_checks(_request(interfaces=[iface]))
        self.assertEqual(errors, [])
        svc.common.resolve_namespace_id.assert_awaited_once_with("Global")

    async def test_interface_level_namespace_is_used_for_single_ip_field(self) -> None:
        svc = _service(_preflight_dispatch())
        iface = {"name": "eth0", "type": "other", "ip_address": "10.0.0.1/24", "namespace": "black"}
        await svc._preflight_checks(_request(interfaces=[iface]))
        svc.common.resolve_namespace_id.assert_awaited_once_with("black")

    async def test_each_namespace_is_resolved_once(self) -> None:
        svc = _service(_preflight_dispatch())
        await svc._preflight_checks(
            _request(interfaces=[_iface("eth0", ips=("10.0.0.1/24", "10.0.1.1/24"))])
        )
        svc.common.resolve_namespace_id.assert_awaited_once_with("Global")

    async def test_invalid_ip_address_is_reported(self) -> None:
        svc = _service(_preflight_dispatch())
        errors = await svc._preflight_checks(_request(interfaces=[_iface(ips=("not-an-ip",))]))
        self.assertTrue(any("not-an-ip" in e for e in errors))

    async def test_missing_parent_prefix_is_reported_when_add_prefix_is_off(self) -> None:
        svc = _service(_preflight_dispatch(prefix_count=0))
        errors = await svc._preflight_checks(_request(interfaces=[_iface()], add_prefix=False))
        self.assertEqual(len(errors), 1)
        self.assertIn("No parent prefix", errors[0])
        self.assertIn("10.0.0.1/24", errors[0])

    async def test_prefix_lookup_uses_the_host_address_like_nautobot(self) -> None:
        """Nautobot picks an IP's parent by containment of its host address (the mask plays no
        part), so any prefix containing the host is a valid parent: query the host, not the
        network."""
        svc = _service(_preflight_dispatch(prefix_count=1))
        await svc._preflight_checks(
            _request(interfaces=[_iface(ips=("10.0.0.5/24",))], add_prefix=False)
        )
        endpoints = [c.args[0] for c in svc.nautobot.rest_request.await_args_list]
        prefix_lookup = next(e for e in endpoints if e.startswith("ipam/prefixes/?"))
        self.assertIn("contains=10.0.0.5&", prefix_lookup)

    async def test_namespace_object_on_the_ip_is_used(self) -> None:
        svc = _service(_preflight_dispatch())
        iface = _iface()
        iface["ip_addresses"] = [{"address": "10.0.0.1/24", "namespace": {"name": "black"}}]
        await svc._preflight_checks(_request(interfaces=[iface]))
        svc.common.resolve_namespace_id.assert_awaited_once_with("black")

    async def test_parent_prefix_present_is_ok(self) -> None:
        svc = _service(_preflight_dispatch(prefix_count=1))
        errors = await svc._preflight_checks(_request(interfaces=[_iface()], add_prefix=False))
        self.assertEqual(errors, [])

    async def test_existing_ip_needs_no_prefix_lookup(self) -> None:
        svc = _service(_preflight_dispatch(prefix_count=0, ip_count=1))
        errors = await svc._preflight_checks(_request(interfaces=[_iface()], add_prefix=False))
        self.assertEqual(errors, [])

    async def test_add_prefix_on_skips_prefix_and_ip_lookups(self) -> None:
        svc = _service(_preflight_dispatch(prefix_count=0))
        errors = await svc._preflight_checks(_request(interfaces=[_iface()], add_prefix=True))
        self.assertEqual(errors, [])
        svc.nautobot.rest_request.assert_not_awaited()

    async def test_failing_lookup_is_skipped_not_reported(self) -> None:
        async def dispatch(endpoint, *a, **k):
            raise NautobotAPIError("Nautobot is down")

        svc = _service(dispatch)
        errors = await svc._preflight_checks(_request(interfaces=[_iface()], add_prefix=False))
        self.assertEqual(errors, [])

    async def test_no_interfaces_means_no_checks(self) -> None:
        svc = _service(_preflight_dispatch())
        self.assertEqual(await svc._preflight_checks(_request()), [])
        svc.common.resolve_namespace_id.assert_not_awaited()

    async def test_dry_run_reports_the_same_problems(self) -> None:
        svc = _service(_preflight_dispatch())
        req = _request(
            role=_UUID,
            status=_UUID,
            location=_UUID,
            device_type=_UUID,
            interfaces=[_iface(type_=None)],
            dry_run=True,
        )
        result = await svc.create_device(req)
        self.assertFalse(result["success"])
        self.assertTrue(any("type is required" in e for e in result["errors"]))

    async def test_real_run_with_errors_creates_nothing(self) -> None:
        svc = _service(_preflight_dispatch())
        result = await svc.create_device(_request(interfaces=[_iface(type_=None)]))
        self.assertFalse(result["success"])
        self.assertFalse(result["dry_run"])
        self.assertIsNone(result["device_id"])
        self.assertTrue(any("type is required" in e for e in result["errors"]))
        posts = [
            c for c in svc.nautobot.rest_request.await_args_list if c.kwargs.get("method") == "POST"
        ]
        self.assertEqual(posts, [])
        svc.interface_manager.update_device_interfaces.assert_not_awaited()

    async def test_real_run_without_errors_still_creates_the_device(self) -> None:
        svc = _service(_preflight_dispatch())
        result = await svc.create_device(_request(interfaces=[_iface()]))
        self.assertTrue(result["success"])
        self.assertEqual(result["device_id"], "dev-1")


class InterfaceStageFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_api_error_after_creation_keeps_the_device_id(self) -> None:
        svc = _service(_preflight_dispatch())
        svc.interface_manager.update_device_interfaces = AsyncMock(
            side_effect=NautobotAPIError("Cannot create IP 10.0.0.1/24: No suitable parent prefix")
        )
        result = await svc.create_device(_request(interfaces=[_iface(), _iface("eth1", ips=())]))
        self.assertTrue(result["success"])
        self.assertEqual(result["device_id"], "dev-1")
        self.assertEqual(result["interfaces_failed"], 2)
        self.assertTrue(any("No suitable parent prefix" in w for w in result["warnings"]))


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

    async def test_secrets_group_in_payload_only_when_set(self) -> None:
        captured: dict = {}

        async def dispatch(*a, **k):
            captured.update(k)
            return {"id": "dev-1"}

        svc = _service(rest_dispatch=dispatch)
        base = dict(role=_UUID, status=_UUID, location=_UUID, device_type=_UUID)
        await svc._create_device(_request(**base))
        self.assertNotIn("secrets_group", captured["data"])
        await svc._create_device(_request(secrets_group=_UUID, **base))
        self.assertEqual(captured["data"]["secrets_group"], _UUID)

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
