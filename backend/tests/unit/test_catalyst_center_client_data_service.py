"""Wired clients from Catalyst Center: request shape, paging and normalisation (mocked client)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from services.catalyst_center.client_data_service import (
    CLIENTS_QUERY_PATH,
    PAGE_LIMIT,
    CatalystCenterClientDataService,
)
from services.catalyst_center.common.exceptions import (
    CatalystCenterAPIError,
    CatalystCenterValidationError,
)


def _row(mac: str = "AA:BB:CC:DD:EE:01", **extra: object) -> dict[str, object]:
    """A client shaped like the published ``Wired`` view example of ``clients/query``."""
    return {
        "id": mac,
        "macAddress": mac,
        "ipv4Address": "10.0.0.5",
        "ipv6Addresses": [],
        "connection": {"vlanId": "10"},
        "connectedNetworkDevice": {
            "connectedNetworkDeviceId": "dev-1",
            "connectedNetworkDeviceName": "sw1",
            "interfaceName": "GigabitEthernet1/0/3",
        },
        "username": "alice",
        **extra,
    }


def _service(*pages: object) -> tuple[CatalystCenterClientDataService, MagicMock]:
    client = MagicMock()
    client.request = AsyncMock(side_effect=[{"response": page} for page in pages])
    service = CatalystCenterClientDataService(client, MagicMock(), clock=lambda: 1_000_000.0)
    return service, client


class RequestShapeTests(unittest.IsolatedAsyncioTestCase):
    async def test_posts_a_connected_wired_query_for_the_switch_id(self) -> None:
        service, client = _service([_row()])
        await service.get_wired_clients("dev-1", lookback_hours=2)
        args, kwargs = client.request.call_args
        self.assertEqual(args[1:], ("POST", CLIENTS_QUERY_PATH))
        body = kwargs["json"]
        self.assertEqual(body["views"], ["Wired"])
        self.assertEqual(body["endTime"], 1_000_000_000)
        self.assertEqual(body["startTime"], 1_000_000_000 - 2 * 3_600_000)
        self.assertEqual(
            body["filters"],
            [
                {"key": "connectedNetworkDeviceId", "operator": "eq", "value": "dev-1"},
                {"key": "type", "operator": "eq", "value": "Wired"},
                {"key": "connectionStatus", "operator": "eq", "value": "connected"},
            ],
        )
        self.assertEqual(body["page"], {"limit": PAGE_LIMIT, "offset": 1})

    async def test_rejects_bad_input_before_any_request(self) -> None:
        service, client = _service()
        for device_id, hours in (("", 24), ("a/b", 24), ("dev-1", 0), ("dev-1", 169)):
            with self.subTest(device_id=device_id, hours=hours):
                with self.assertRaises(CatalystCenterValidationError):
                    await service.get_wired_clients(device_id, lookback_hours=hours)
        client.request.assert_not_called()


class PagingTests(unittest.IsolatedAsyncioTestCase):
    async def test_pages_until_a_short_page(self) -> None:
        full = [_row(f"aa:bb:cc:dd:{i // 256:02x}:{i % 256:02x}") for i in range(PAGE_LIMIT)]
        service, client = _service(full, [_row("aa:bb:cc:dd:ff:ff")])
        clients = await service.get_wired_clients("dev-1", lookback_hours=24)
        self.assertEqual(len(clients), PAGE_LIMIT + 1)
        offsets = [call.kwargs["json"]["page"]["offset"] for call in client.request.call_args_list]
        self.assertEqual(offsets, [1, PAGE_LIMIT + 1])

    async def test_empty_response_is_no_clients(self) -> None:
        service, _ = _service([])
        self.assertEqual(await service.get_wired_clients("dev-1", lookback_hours=24), ())

    async def test_unexpected_body_is_an_error(self) -> None:
        client = MagicMock()
        client.request = AsyncMock(return_value={"response": {"oops": 1}})
        service = CatalystCenterClientDataService(client, MagicMock())
        with self.assertRaises(CatalystCenterAPIError):
            await service.get_wired_clients("dev-1", lookback_hours=24)

    async def test_endless_pages_stop_with_an_error(self) -> None:
        full = [_row()] * PAGE_LIMIT
        client = MagicMock()
        client.request = AsyncMock(return_value={"response": full})
        service = CatalystCenterClientDataService(client, MagicMock())
        with self.assertRaisesRegex(CatalystCenterAPIError, "more than"):
            await service.get_wired_clients("dev-1", lookback_hours=24)


class NormalisationTests(unittest.IsolatedAsyncioTestCase):
    async def test_fields_are_read_from_the_published_paths_and_whitelisted(self) -> None:
        service, _ = _service([_row(ipv6Addresses=["2001:db8::1", "not-an-ip", "2001:DB8::1"])])
        (client,) = await service.get_wired_clients("dev-1", lookback_hours=24)
        self.assertEqual(client.mac_address, "AA:BB:CC:DD:EE:01")
        self.assertEqual(client.ip_addresses, ("10.0.0.5", "2001:db8::1"))
        self.assertEqual((client.vlan, client.port), ("10", "GigabitEthernet1/0/3"))
        self.assertEqual(
            (client.connected_device_id, client.connected_device_name), ("dev-1", "sw1")
        )
        self.assertNotIn("alice", str(client.model_dump()))

    async def test_non_host_addresses_are_dropped_private_ones_kept(self) -> None:
        service, _ = _service(
            [
                _row(
                    ipv4Address="192.168.1.9",
                    ipv6Addresses=["fe80::1", "::", "::1", "ff02::1", "2001:db8::2"],
                ),
                _row("aa:bb:cc:dd:ee:02", ipv4Address="0.0.0.0"),
            ]
        )
        first, second = await service.get_wired_clients("dev-1", lookback_hours=24)
        self.assertEqual(first.ip_addresses, ("192.168.1.9", "2001:db8::2"))
        self.assertEqual(second.ip_addresses, ())

    async def test_missing_values_are_none(self) -> None:
        service, _ = _service([{"id": "aa:bb:cc:dd:ee:02"}, "junk"])
        (client,) = await service.get_wired_clients("dev-1", lookback_hours=24)
        self.assertEqual(client.mac_address, "aa:bb:cc:dd:ee:02")
        self.assertEqual(client.ip_addresses, ())
        self.assertIsNone(client.vlan)
        self.assertIsNone(client.port)
        self.assertIsNone(client.connected_device_id)
