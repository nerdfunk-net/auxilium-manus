"""Unit tests for services/nautobot/devices/uuid_resolver.py against a mocked
``DeviceCommonService`` — no network, no real resolver calls."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from services.nautobot.devices.uuid_resolver import (
    OBJECTVAR_MODEL_TO_RESOURCE_TYPE,
    UUID_RESOURCE_TYPES,
    content_type_required,
    resolve_nautobot_uuid,
)

_UUID = "550e8400-e29b-41d4-a716-446655440000"


def _common() -> MagicMock:
    common = MagicMock()
    common.resolve_location_id = AsyncMock(return_value=_UUID)
    common.resolve_role_id_for_content_type = AsyncMock(return_value=_UUID)
    common.resolve_status_id = AsyncMock(return_value=_UUID)
    common.resolve_platform_id = AsyncMock(return_value=_UUID)
    common.resolve_device_id = AsyncMock(return_value=_UUID)
    common.resolve_device_type_id = AsyncMock(return_value=_UUID)
    common.resolve_namespace_id = AsyncMock(return_value=_UUID)
    common.resolve_rack_id = AsyncMock(return_value=_UUID)
    return common


class ResolveNautobotUuidTests(unittest.IsolatedAsyncioTestCase):
    async def test_location_dispatch(self) -> None:
        common = _common()
        result = await resolve_nautobot_uuid(common, "location", "NYC-DC1")
        self.assertEqual(result, _UUID)
        common.resolve_location_id.assert_awaited_once_with("NYC-DC1")

    async def test_role_dispatch_defaults_content_type_to_device(self) -> None:
        common = _common()
        await resolve_nautobot_uuid(common, "role", "core-router")
        common.resolve_role_id_for_content_type.assert_awaited_once_with(
            "core-router", "dcim.device"
        )

    async def test_role_dispatch_passes_explicit_content_type(self) -> None:
        common = _common()
        await resolve_nautobot_uuid(common, "role", "edge", content_type="dcim.interface")
        common.resolve_role_id_for_content_type.assert_awaited_once_with(
            "edge", "dcim.interface"
        )

    async def test_status_dispatch_defaults_content_type_to_device(self) -> None:
        common = _common()
        await resolve_nautobot_uuid(common, "status", "Active")
        common.resolve_status_id.assert_awaited_once_with("Active", "dcim.device")

    async def test_device_dispatch_uses_device_name_kwarg(self) -> None:
        common = _common()
        await resolve_nautobot_uuid(common, "device", "router1")
        common.resolve_device_id.assert_awaited_once_with(device_name="router1")

    async def test_platform_device_type_namespace_rack_dispatch(self) -> None:
        common = _common()
        await resolve_nautobot_uuid(common, "platform", "ios")
        common.resolve_platform_id.assert_awaited_once_with("ios")
        await resolve_nautobot_uuid(common, "device_type", "ISR4451")
        common.resolve_device_type_id.assert_awaited_once_with("ISR4451")
        await resolve_nautobot_uuid(common, "namespace", "Global")
        common.resolve_namespace_id.assert_awaited_once_with("Global")
        await resolve_nautobot_uuid(common, "rack", "Rack-1")
        common.resolve_rack_id.assert_awaited_once_with("Rack-1")

    async def test_unresolved_value_raises_value_error(self) -> None:
        common = _common()
        common.resolve_location_id = AsyncMock(return_value=None)
        with self.assertRaises(ValueError):
            await resolve_nautobot_uuid(common, "location", "Nowhere")

    async def test_empty_value_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            await resolve_nautobot_uuid(_common(), "location", "   ")

    async def test_unknown_resource_type_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            await resolve_nautobot_uuid(_common(), "vlan", "100")


class ContentTypeRequiredTests(unittest.TestCase):
    def test_role_and_status_require_content_type(self) -> None:
        self.assertTrue(content_type_required("role"))
        self.assertTrue(content_type_required("status"))

    def test_other_resource_types_do_not(self) -> None:
        for resource_type in UUID_RESOURCE_TYPES - {"role", "status"}:
            self.assertFalse(content_type_required(resource_type))


class ObjectVarModelMapTests(unittest.TestCase):
    def test_every_mapped_value_is_a_known_resource_type(self) -> None:
        for resource_type in OBJECTVAR_MODEL_TO_RESOURCE_TYPE.values():
            self.assertIn(resource_type, UUID_RESOURCE_TYPES)


if __name__ == "__main__":
    unittest.main()
