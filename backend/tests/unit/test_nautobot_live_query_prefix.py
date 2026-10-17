"""S4-06: an IP-prefix filter can never carry GraphQL syntax into the query."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from services.sources.nautobot.live_query_mixin import (
    NautobotLiveQueryMixin,
    _split_prefix_filter,
)

PAYLOAD = (
    '10.0.0.0/8 Global") { id } injected: secrets { name } ghost: prefixes(prefix: "1.1.1.1/32'
)


class SplitPrefixFilterTests(unittest.TestCase):
    def test_valid_values_pass(self) -> None:
        self.assertEqual(_split_prefix_filter("10.0.0.0/8"), ("10.0.0.0/8", None))
        self.assertEqual(
            _split_prefix_filter("192.168.183.0/24 Global"), ("192.168.183.0/24", "Global")
        )
        self.assertEqual(_split_prefix_filter("2001:db8::/32")[0], "2001:db8::/32")

    def test_graphql_payload_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _split_prefix_filter(PAYLOAD)

    def test_hostile_cidr_and_namespace_are_rejected(self) -> None:
        for bad in ('10.0.0.0/8"}', "not-a-cidr", '10.0.0.0/8 Glo"bal', "10.0.0.0/8 a{b}", ""):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                _split_prefix_filter(bad)


class QueryTextTests(unittest.IsolatedAsyncioTestCase):
    def _service(self) -> NautobotLiveQueryMixin:
        service = NautobotLiveQueryMixin.__new__(NautobotLiveQueryMixin)
        service._nautobot = MagicMock()
        service._nautobot.graphql_query = AsyncMock(return_value={"data": {"prefixes": []}})
        service._credentials = MagicMock()
        return service

    async def test_hostile_prefix_never_reaches_nautobot(self) -> None:
        service = self._service()
        with self.assertRaises(ValueError):
            await service._query_devices_by_ip_prefix(PAYLOAD)
        with self.assertRaises(ValueError):
            await service._query_devices_by_primary_prefix(PAYLOAD)
        service._nautobot.graphql_query.assert_not_called()

    async def test_valid_prefix_is_placed_in_the_query(self) -> None:
        service = self._service()
        await service._query_devices_by_ip_prefix("10.0.0.0/8 Global", "within")
        query = service._nautobot.graphql_query.call_args.args[0]
        self.assertIn('within: "10.0.0.0/8", namespace: "Global"', query)


class InvalidFilterInputTests(unittest.TestCase):
    def test_malformed_prefix_raises_invalid_filter_input(self) -> None:
        from core.domain_exceptions import InvalidFilterInputError, ValidationFailedError

        with self.assertRaises(InvalidFilterInputError) as ctx:
            _split_prefix_filter("not-a-cidr")
        self.assertIsInstance(ctx.exception, ValidationFailedError)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "invalid IP prefix")

