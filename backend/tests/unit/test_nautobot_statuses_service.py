"""Tests for services/nautobot/statuses.py."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from services.nautobot.statuses import NautobotStatusesService


class StatusesServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_lists_statuses_of_the_content_type(self) -> None:
        client = MagicMock()
        client.rest_request = AsyncMock(
            return_value={"results": [{"id": "1", "name": "Active"}], "next": None}
        )
        result = await NautobotStatusesService(client).list_statuses("ipam.ipaddress")
        self.assertEqual(result, [{"id": "1", "name": "Active"}])
        endpoint = client.rest_request.call_args.kwargs["endpoint"]
        self.assertTrue(endpoint.startswith("extras/statuses/?"))
        self.assertIn("content_types=ipam.ipaddress", endpoint)

    async def test_refuses_a_content_type_outside_the_allow_list(self) -> None:
        client = MagicMock()
        client.rest_request = AsyncMock()
        with self.assertRaises(ValueError):
            await NautobotStatusesService(client).list_statuses("../x")  # type: ignore[arg-type]
        client.rest_request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
