"""Unit tests for the inventory "Primary Prefix" filter.

Verifies that _query_devices_by_primary_prefix only returns devices whose
primary IPv4 address falls in the given prefix — i.e. only devices listed
under an ip_addresses entry's primary_ip4_for — and that the evaluator
wires the "primary_prefix" field/operator through correctly.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from models.sources_nautobot import LogicalCondition
from services.nautobot.credentials import NautobotCredentials
from services.sources.nautobot.evaluator import NautobotSourceEvaluator
from services.sources.nautobot.query_service import NautobotSourceQueryService


def _graphql_response(ip_addresses):
    return {"data": {"ip_addresses": ip_addresses}}


def _query_service(graphql_query: AsyncMock | None = None) -> NautobotSourceQueryService:
    nautobot = MagicMock()
    if graphql_query is not None:
        nautobot.graphql_query = graphql_query
    credentials = NautobotCredentials(
        url="https://nautobot.example",
        token="test-token",
    )
    return NautobotSourceQueryService(nautobot, credentials)


class TestPrimaryPrefixQuery(unittest.IsolatedAsyncioTestCase):
    """Test NautobotSourceQueryService._query_devices_by_primary_prefix."""

    async def test_only_returns_devices_listed_under_primary_ip4_for(self):
        """An address with an empty primary_ip4_for must not surface a device."""
        graphql_query = AsyncMock(
            return_value=_graphql_response(
                [
                    {
                        "address": "192.168.178.1/24",
                        "primary_ip4_for": [{"id": "dev-1", "name": "lab-001"}],
                    },
                    {
                        # Address is in the prefix but not anyone's primary IP
                        "address": "192.168.178.2/24",
                        "primary_ip4_for": [],
                    },
                    {
                        "address": "192.168.178.3/24",
                        "primary_ip4_for": [{"id": "dev-3", "name": "lab-003"}],
                    },
                ]
            )
        )
        query_service = _query_service(graphql_query)

        devices = await query_service._query_devices_by_primary_prefix(
            "192.168.178.0/30", "within_include"
        )

        device_ids = {device.id for device in devices}
        self.assertEqual(device_ids, {"dev-1", "dev-3"})

    async def test_within_include_operator_maps_to_prefix_graphql_arg(self):
        """ip_addresses(...) only accepts `prefix`, not `within_include`."""
        graphql_query = AsyncMock(return_value=_graphql_response([]))
        query_service = _query_service(graphql_query)

        await query_service._query_devices_by_primary_prefix(
            "10.0.0.0/24", "within_include"
        )

        query_arg = graphql_query.call_args[0][0]
        self.assertIn('prefix: "10.0.0.0/24"', query_arg)
        self.assertNotIn("within_include:", query_arg)
        self.assertNotIn("within:", query_arg)

    async def test_empty_prefix_returns_empty_list(self):
        query_service = _query_service()
        devices = await query_service._query_devices_by_primary_prefix("", "within")
        self.assertEqual(devices, [])


class TestPrimaryPrefixEvaluator(unittest.IsolatedAsyncioTestCase):
    """Test NautobotSourceEvaluator._execute_condition wiring for primary_prefix."""

    async def test_condition_delegates_to_primary_prefix_query(self):
        graphql_query = AsyncMock(
            return_value=_graphql_response(
                [
                    {
                        "address": "192.168.178.1/24",
                        "primary_ip4_for": [{"id": "dev-1", "name": "lab-001"}],
                    }
                ]
            )
        )
        query_service = _query_service(graphql_query)
        evaluator = NautobotSourceEvaluator(query_service)

        condition = LogicalCondition(
            field="primary_prefix",
            operator="within_include",
            value="192.168.178.0/30",
        )

        device_ids, op_count, devices_dict = await evaluator._execute_condition(
            condition
        )

        self.assertEqual(device_ids, {"dev-1"})
        self.assertEqual(op_count, 1)
        self.assertIn("dev-1", devices_dict)


if __name__ == "__main__":
    unittest.main()
