"""Tests for resolve_nautobot_device_id (backend/workflow_steps/common/nautobot_resolve.py).

Regression coverage for a bug where a non-Nautobot source (e.g. get-ise-devices)
whose own device id happens to be UUID-shaped got that id trusted as a Nautobot
device UUID with no verification, short-circuiting name/IP resolution entirely.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from models.workflow_context import Capability, DeviceContext, DeviceStatus
from workflow_steps.common.nautobot_resolve import resolve_nautobot_device_id

_NAUTOBOT_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_ISE_UUID = "957a31a0-8294-11f1-b5fd-3eac1c258930"  # UUID-shaped, but ISE-generated


def _device(**overrides) -> DeviceContext:
    defaults = dict(
        id="dev-1",
        name="router1",
        hostname="router1",
        primary_ip4="10.0.0.1",
        source="",
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )
    defaults.update(overrides)
    return DeviceContext(**defaults)


class ResolveNautobotDeviceIdTests(unittest.IsolatedAsyncioTestCase):
    async def test_nautobot_sourced_uuid_passes_through_without_a_query(self) -> None:
        nautobot_service = MagicMock()
        nautobot_service.graphql_query = AsyncMock()
        device = _device(id=_NAUTOBOT_UUID, source="nautobot")

        result = await resolve_nautobot_device_id(
            nautobot_service=nautobot_service,
            credentials=MagicMock(),
            device=device,
        )

        self.assertEqual(result, _NAUTOBOT_UUID)
        nautobot_service.graphql_query.assert_not_called()

    async def test_foreign_uuid_shaped_id_does_not_pass_through(self) -> None:
        """A non-Nautobot source's UUID-shaped id (e.g. ISE) must not be
        trusted as a Nautobot id — it must fall through to name resolution."""
        nautobot_service = MagicMock()
        nautobot_service.graphql_query = AsyncMock(
            return_value={"data": {"devices": [{"id": _NAUTOBOT_UUID, "name": "router1"}]}}
        )
        device = _device(id=_ISE_UUID, name="router1", source="ise")

        result = await resolve_nautobot_device_id(
            nautobot_service=nautobot_service,
            credentials=MagicMock(),
            device=device,
        )

        self.assertEqual(result, _NAUTOBOT_UUID)
        nautobot_service.graphql_query.assert_called_once()
        query, variables, _ = nautobot_service.graphql_query.call_args.args
        self.assertIn("DevicesByName", query)
        self.assertEqual(variables, {"names": ["router1"]})

    async def test_git_sourced_synthetic_id_resolves_by_name(self) -> None:
        nautobot_service = MagicMock()
        nautobot_service.graphql_query = AsyncMock(
            return_value={"data": {"devices": [{"id": _NAUTOBOT_UUID, "name": "router1"}]}}
        )
        device = _device(id="git-deadbeef", name="router1", source="git")

        result = await resolve_nautobot_device_id(
            nautobot_service=nautobot_service,
            credentials=MagicMock(),
            device=device,
        )

        self.assertEqual(result, _NAUTOBOT_UUID)

    async def test_falls_back_to_primary_ip4_when_name_lookup_finds_nothing(self) -> None:
        nautobot_service = MagicMock()
        nautobot_service.graphql_query = AsyncMock(
            side_effect=[
                {"data": {"devices": []}},
                {
                    "data": {
                        "devices": [
                            {
                                "id": _NAUTOBOT_UUID,
                                "name": "some-other-name",
                                "primary_ip4": {"address": "10.0.0.1/32"},
                            }
                        ]
                    }
                },
            ]
        )
        device = _device(id=_ISE_UUID, name="lab", primary_ip4="10.0.0.1", source="ise")

        result = await resolve_nautobot_device_id(
            nautobot_service=nautobot_service,
            credentials=MagicMock(),
            device=device,
        )

        self.assertEqual(result, _NAUTOBOT_UUID)
        self.assertEqual(nautobot_service.graphql_query.await_count, 2)

    async def test_returns_none_when_neither_name_nor_ip_match(self) -> None:
        nautobot_service = MagicMock()
        nautobot_service.graphql_query = AsyncMock(return_value={"data": {"devices": []}})
        device = _device(id=_ISE_UUID, name="lab", primary_ip4="10.0.0.1", source="ise")

        result = await resolve_nautobot_device_id(
            nautobot_service=nautobot_service,
            credentials=MagicMock(),
            device=device,
        )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
