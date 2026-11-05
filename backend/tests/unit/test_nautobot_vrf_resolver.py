"""Tests for NetworkResolver.resolve_vrf_id."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from services.nautobot.resolvers.network_resolver import NetworkResolver

_UUID = "11111111-2222-3333-4444-555555555555"


def _resolver(response: object) -> NetworkResolver:
    nautobot = MagicMock()
    nautobot.rest_request = AsyncMock(return_value=response)
    return NetworkResolver(nautobot)


class ResolveVrfIdTests(unittest.IsolatedAsyncioTestCase):
    async def test_uuid_passes_through_without_a_request(self) -> None:
        resolver = _resolver({})
        self.assertEqual(await resolver.resolve_vrf_id(_UUID), _UUID)
        resolver.nautobot.rest_request.assert_not_awaited()

    async def test_name_is_looked_up_exactly(self) -> None:
        resolver = _resolver(
            {"results": [{"id": "v1", "name": "MGMT-2"}, {"id": "v2", "name": "MGMT"}]}
        )
        self.assertEqual(await resolver.resolve_vrf_id("MGMT"), "v2")
        endpoint = resolver.nautobot.rest_request.await_args.kwargs["endpoint"]
        self.assertTrue(endpoint.startswith("ipam/vrfs/?"))
        self.assertIn("name=MGMT", endpoint)

    async def test_unknown_name_is_none(self) -> None:
        self.assertIsNone(await _resolver({"results": []}).resolve_vrf_id("NOPE"))

    async def test_blank_name_is_none(self) -> None:
        resolver = _resolver({})
        self.assertIsNone(await resolver.resolve_vrf_id("  "))
        resolver.nautobot.rest_request.assert_not_awaited()
