"""S4-12: a rack name stays one query parameter."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from services.nautobot.resolvers.metadata_resolver import MetadataResolver


class RackQueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_rack_name_with_ampersand_stays_one_parameter(self) -> None:
        nautobot = MagicMock()
        nautobot.rest_request = AsyncMock(return_value={"count": 0})
        resolver = MetadataResolver(nautobot)
        await resolver.resolve_rack_id("R1&location=evil", location="site 1")
        endpoint = nautobot.rest_request.call_args.kwargs["endpoint"]
        self.assertIn("name=R1%26location%3Devil", endpoint)
        self.assertEqual(endpoint.count("&location="), 1)
        self.assertIn("location=site+1", endpoint)
