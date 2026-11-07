"""NautobotPrefixReader: all prefixes of a Nautobot, paged, via GraphQL (read-only)."""

from __future__ import annotations

import unittest
from typing import Any

from services.nautobot.common.exceptions import NautobotAPIError
from services.nautobot.prefix_reader import MAX_PREFIXES, PAGE_SIZE, NautobotPrefixReader


def _row(
    prefix: str, namespace: str = "Global", status: str = "Active", type_: str = "network"
) -> dict:
    return {
        "prefix": prefix,
        "type": type_,
        "status": {"name": status},
        "namespace": {"name": namespace},
    }


class FakeClient:
    def __init__(self, pages: list[Any]) -> None:
        self.pages = pages
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def graphql_query(self, query: str, variables: dict[str, Any] | None = None) -> Any:
        self.calls.append((query, variables))
        page = self.pages[len(self.calls) - 1]
        if isinstance(page, Exception):
            raise page
        return page


def _data(*rows: dict) -> dict:
    return {"data": {"prefixes": list(rows)}}


class ReaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_prefixes_with_namespace_status_and_type(self) -> None:
        reader = NautobotPrefixReader(
            FakeClient([_data(_row("10.1.1.0/24", "Heroes", "Reserved", "pool"))])
        )
        (prefix,) = await reader.list_prefixes()
        self.assertEqual(
            (prefix.prefix, prefix.namespace, prefix.status, prefix.type),
            ("10.1.1.0/24", "Heroes", "Reserved", "pool"),
        )

    async def test_prefixes_are_normalised_to_the_network_form(self) -> None:
        reader = NautobotPrefixReader(
            FakeClient([_data(_row("10.1.1.5/24"), _row("2001:DB8::/64"))])
        )
        self.assertEqual(
            [p.prefix for p in await reader.list_prefixes()], ["10.1.1.0/24", "2001:db8::/64"]
        )

    async def test_pages_until_a_short_page(self) -> None:
        full = _data(*[_row(f"10.{i // 256}.{i % 256}.0/24") for i in range(PAGE_SIZE)])
        client = FakeClient([full, _data(_row("192.168.0.0/24"))])
        prefixes = await NautobotPrefixReader(client).list_prefixes()
        self.assertEqual(len(prefixes), PAGE_SIZE + 1)
        self.assertEqual(
            [c[1] for c in client.calls],
            [
                {"limit": PAGE_SIZE, "offset": 0},
                {"limit": PAGE_SIZE, "offset": PAGE_SIZE},
            ],
        )

    async def test_an_empty_nautobot_gives_no_prefixes(self) -> None:
        self.assertEqual(await NautobotPrefixReader(FakeClient([_data()])).list_prefixes(), ())

    async def test_graphql_errors_fail_instead_of_looking_like_no_prefixes(self) -> None:
        body = {"data": {"prefixes": [_row("10.0.0.0/8")]}, "errors": [{"message": "boom"}]}
        with self.assertRaises(NautobotAPIError) as caught:
            await NautobotPrefixReader(FakeClient([body])).list_prefixes()
        self.assertEqual(caught.exception.code, "graphql_error")

    async def test_a_body_without_the_prefix_list_is_an_error(self) -> None:
        for body in ({}, {"data": None}, {"data": {}}, {"data": {"prefixes": "x"}}, None):
            with self.subTest(body=body), self.assertRaises(NautobotAPIError):
                await NautobotPrefixReader(FakeClient([body])).list_prefixes()

    async def test_a_row_that_is_not_a_prefix_is_skipped(self) -> None:
        reader = NautobotPrefixReader(
            FakeClient([_data({"prefix": "garbage"}, _row("10.0.0.0/8"), {})])
        )
        self.assertEqual([p.prefix for p in await reader.list_prefixes()], ["10.0.0.0/8"])

    async def test_the_cap_fails_instead_of_truncating(self) -> None:
        self.assertGreater(MAX_PREFIXES, PAGE_SIZE)
        reader = NautobotPrefixReader(FakeClient([_data(_row("10.0.0.0/8"))]), max_prefixes=0)
        with self.assertRaises(NautobotAPIError) as caught:
            await reader.list_prefixes()
        self.assertEqual(caught.exception.code, "too_many_objects")

    async def test_a_transport_error_propagates(self) -> None:
        with self.assertRaises(NautobotAPIError):
            await NautobotPrefixReader(
                FakeClient([NautobotAPIError("down", code="transport")])
            ).list_prefixes()
