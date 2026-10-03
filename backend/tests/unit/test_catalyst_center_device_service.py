"""Tests for CatalystCenterDeviceService: normalization, pagination, version gating."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from pydantic import ValidationError

from services.catalyst_center.common.exceptions import (
    CatalystCenterNotFoundError,
    CatalystCenterValidationError,
)
from services.catalyst_center.common.version import parse_release
from services.catalyst_center.credentials import CatalystCenterCredentials
from services.catalyst_center.device_service import (
    DEVICE_PAGE_SIZE,
    CatalystCenterDeviceService,
)

DEVICES = "/dna/intent/api/v1/network-device"


def _creds() -> CatalystCenterCredentials:
    return CatalystCenterCredentials("https://10.10.20.85", "admin", "pw")


def _raw(i: int, **extra) -> dict:
    return {
        "id": f"uuid-{i}",
        "hostname": f"sw{i}.lab.local",
        "managementIpAddress": f"10.0.0.{i}",
        "macAddress": f"aa:bb:cc:dd:ee:0{i % 10}",
        "platformId": "C9300-24P",
        "family": "Switches and Hubs",
        "type": "Cisco Catalyst 9300 Switch",
        "serialNumber": f"FOC{i:04d}",
        "softwareVersion": "17.9.4",
        "softwareType": "IOS-XE",
        "role": "ACCESS",
        "reachabilityStatus": "Reachable",
        "collectionStatus": "Managed",
        **extra,
    }


def _service(client: AsyncMock) -> CatalystCenterDeviceService:
    return CatalystCenterDeviceService(client, _creds())


class DeviceNormalizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_device_maps_fields(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": _raw(1)}
        device = await _service(client).get_device("uuid-1")

        client.request.assert_awaited_once_with(_creds(), "GET", f"{DEVICES}/uuid-1")
        self.assertEqual(device.id, "uuid-1")
        self.assertEqual(device.hostname, "sw1.lab.local")
        self.assertEqual(device.management_ip, "10.0.0.1")
        self.assertEqual(device.platform_id, "C9300-24P")
        self.assertEqual(device.software_type, "IOS-XE")
        self.assertEqual(device.serial_number, "FOC0001")
        self.assertEqual(device.raw["role"], "ACCESS")

    async def test_missing_optional_fields_become_none(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": {"id": "u"}}
        device = await _service(client).get_device("u")
        self.assertIsNone(device.hostname)
        self.assertIsNone(device.management_ip)

    async def test_get_device_rejects_payload_without_id(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": {"hostname": "x"}}
        with self.assertRaises(CatalystCenterValidationError):
            await _service(client).get_device("u")

    async def test_get_device_not_found_propagates(self) -> None:
        client = AsyncMock()
        client.request.side_effect = CatalystCenterNotFoundError("nope")
        with self.assertRaises(CatalystCenterNotFoundError):
            await _service(client).get_device("u")

    async def test_models_are_immutable(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": _raw(1)}
        device = await _service(client).get_device("uuid-1")
        with self.assertRaises(ValidationError):
            device.hostname = "other"  # type: ignore[misc]


class ListDevicesTests(unittest.IsolatedAsyncioTestCase):
    async def test_paginates_until_short_page(self) -> None:
        full = [_raw(i) for i in range(DEVICE_PAGE_SIZE)]
        client = AsyncMock()
        client.request.side_effect = [
            {"response": full},
            {"response": [_raw(9001), _raw(9002)]},
        ]
        devices = await _service(client).list_devices()

        self.assertEqual(len(devices), DEVICE_PAGE_SIZE + 2)
        first, second = client.request.await_args_list
        self.assertEqual(first.kwargs["params"], {"offset": 1, "limit": DEVICE_PAGE_SIZE})
        self.assertEqual(
            second.kwargs["params"], {"offset": 1 + DEVICE_PAGE_SIZE, "limit": DEVICE_PAGE_SIZE}
        )

    async def test_empty_result(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": []}
        self.assertEqual(await _service(client).list_devices(), ())
        self.assertEqual(client.request.await_count, 1)

    async def test_filters_become_query_params(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": []}
        await _service(client).list_devices(
            hostname="sw1.*", management_ip="10.0.0.1", family="Routers", role="CORE"
        )
        params = client.request.await_args.kwargs["params"]
        self.assertEqual(params["hostname"], "sw1.*")
        self.assertEqual(params["managementIpAddress"], "10.0.0.1")
        self.assertEqual(params["family"], "Routers")
        self.assertEqual(params["role"], "CORE")

    async def test_unset_filters_are_omitted(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": []}
        await _service(client).list_devices()
        self.assertEqual(set(client.request.await_args.kwargs["params"]), {"offset", "limit"})

    async def test_max_devices_truncates_and_stops_early(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": [_raw(i) for i in range(DEVICE_PAGE_SIZE)]}
        devices = await _service(client).list_devices(max_devices=3)
        self.assertEqual(len(devices), 3)
        self.assertEqual(client.request.await_count, 1)

    async def test_non_list_response_is_rejected(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": {"oops": 1}}
        with self.assertRaises(CatalystCenterValidationError):
            await _service(client).list_devices()

    async def test_runaway_pagination_is_bounded(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": [_raw(i) for i in range(DEVICE_PAGE_SIZE)]}
        with self.assertRaises(CatalystCenterValidationError):
            await _service(client).list_devices()


class FindDevicesTests(unittest.IsolatedAsyncioTestCase):
    async def test_find_by_names_matches_exactly_case_insensitive(self) -> None:
        client = AsyncMock()
        client.request.return_value = {
            "response": [_raw(1, hostname="r1"), _raw(2, hostname="r10"), _raw(3, hostname="R1")]
        }
        devices = await _service(client).find_by_names(["r1"])
        self.assertEqual([d.id for d in devices], ["uuid-1", "uuid-3"])

    async def test_find_by_names_skips_blanks_and_dedupes(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": [_raw(1, hostname="r1")]}
        devices = await _service(client).find_by_names(["r1", "  ", "r1"])
        self.assertEqual(len(devices), 1)
        self.assertEqual(client.request.await_count, 1)

    async def test_find_by_ip_uses_ip_endpoint(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": _raw(1)}
        device = await _service(client).find_by_ip("10.0.0.1")
        client.request.assert_awaited_once_with(_creds(), "GET", f"{DEVICES}/ip-address/10.0.0.1")
        self.assertEqual(device.id, "uuid-1")

    async def test_find_by_ip_not_found_returns_none(self) -> None:
        client = AsyncMock()
        client.request.side_effect = CatalystCenterNotFoundError("nope")
        self.assertIsNone(await _service(client).find_by_ip("10.0.0.9"))

    async def test_find_by_ip_rejects_invalid_address(self) -> None:
        client = AsyncMock()
        with self.assertRaises(CatalystCenterValidationError):
            await _service(client).find_by_ip("10.0.0.1/../x")
        client.request.assert_not_called()


class CountAndVersionTests(unittest.IsolatedAsyncioTestCase):
    async def test_unfiltered_count(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": 42}
        self.assertEqual(await _service(client).count_devices(), 42)
        client.get_release.assert_not_called()

    async def test_filtered_count_uses_endpoint_on_2_3_7(self) -> None:
        client = AsyncMock()
        client.get_release.return_value = parse_release("2.3.7.9")
        client.request.return_value = {"response": 5}
        count = await _service(client).count_devices(hostname="sw.*")
        self.assertEqual(count, 5)
        call = client.request.await_args
        self.assertEqual(call.args[2], f"{DEVICES}/count")
        self.assertEqual(call.kwargs["params"], {"hostname": "sw.*"})

    async def test_filtered_count_falls_back_to_listing_on_2_3_3(self) -> None:
        client = AsyncMock()
        client.get_release.return_value = parse_release("2.3.3.6")
        client.request.return_value = {"response": [_raw(1), _raw(2)]}
        count = await _service(client).count_devices(hostname="sw.*")
        self.assertEqual(count, 2)
        self.assertEqual(client.request.await_args.args[2], DEVICES)

    async def test_release_is_fetched_once(self) -> None:
        client = AsyncMock()
        client.get_release.return_value = parse_release("2.3.7.9")
        client.request.return_value = {"response": 1}
        service = _service(client)
        await service.count_devices(hostname="a")
        await service.count_devices(hostname="b")
        client.get_release.assert_awaited_once()

    async def test_test_connection_returns_release(self) -> None:
        client = AsyncMock()
        client.get_release.return_value = parse_release("3.1.6")
        release = await _service(client).test_connection()
        self.assertEqual(release.as_tuple(), (3, 1, 6, 0))
