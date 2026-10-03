"""Tests for CatalystCenterDeviceService: normalization, pagination, version gating."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from pydantic import ValidationError

from services.catalyst_center.common.exceptions import (
    CatalystCenterAuthError,
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

    async def test_unknown_release_falls_back_to_listing(self) -> None:
        client = AsyncMock()
        client.get_release.side_effect = CatalystCenterValidationError("no release")
        client.request.return_value = {"response": [_raw(1), _raw(2), _raw(3)]}
        count = await _service(client).count_devices(hostname="sw.*")
        self.assertEqual(count, 3)
        self.assertEqual(client.request.await_args.args[2], DEVICES)

    async def test_unknown_release_is_looked_up_once(self) -> None:
        client = AsyncMock()
        client.get_release.side_effect = CatalystCenterValidationError("no release")
        client.request.return_value = {"response": []}
        service = _service(client)
        await service.count_devices(hostname="a")
        await service.count_devices(hostname="b")
        client.get_release.assert_awaited_once()

    async def test_test_connection_returns_reported_version_label(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": {"installedVersion": "3.722.75335"}}
        label = await _service(client).test_connection()
        self.assertEqual(label, "3.722.75335")
        self.assertEqual(
            client.request.await_args.args[1:3], ("GET", "/dna/intent/api/v1/dnac-release")
        )

    async def test_test_connection_without_version_returns_none(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": {}}
        self.assertIsNone(await _service(client).test_connection())

    async def test_test_connection_propagates_auth_failure(self) -> None:
        client = AsyncMock()
        client.request.side_effect = CatalystCenterAuthError("bad credentials")
        with self.assertRaises(CatalystCenterAuthError):
            await _service(client).test_connection()


from services.catalyst_center.common.exceptions import (  # noqa: E402
    CatalystCenterTooManyDevicesError,
)
from services.catalyst_center.device_filters import CatalystCenterDeviceFilters  # noqa: E402


def _filters(**raw) -> CatalystCenterDeviceFilters:
    return CatalystCenterDeviceFilters.from_config(raw)


class ListFilterKwargTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_values_are_passed_as_repeated_params(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": []}
        await _service(client).list_devices(hostname=["sw1", "sw2"])
        self.assertEqual(client.request.await_args.kwargs["params"]["hostname"], ["sw1", "sw2"])

    async def test_extra_filter_kinds_map_to_api_names(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": []}
        await _service(client).list_devices(
            platform_id="C9300",
            series="S",
            device_type="T",
            software_version="17.9.*",
            collection_status="Managed",
        )
        params = client.request.await_args.kwargs["params"]
        self.assertEqual(params["platformId"], "C9300")
        self.assertEqual(params["series"], "S")
        self.assertEqual(params["type"], "T")
        self.assertEqual(params["softwareVersion"], "17.9.*")
        self.assertEqual(params["collectionStatus"], "Managed")


class SearchDevicesTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_filter_params_and_pagination(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": [_raw(1)]}
        devices = await _service(client).search_devices(
            _filters(hostnames=["sw1.*", "sw2.*"], roles=["ACCESS"])
        )
        self.assertEqual([d.id for d in devices], ["uuid-1"])
        params = client.request.await_args.kwargs["params"]
        self.assertEqual(params["hostname"], ["sw1.*", "sw2.*"])
        self.assertEqual(params["role"], ["ACCESS"])
        self.assertEqual(params["offset"], 1)
        self.assertEqual(params["limit"], DEVICE_PAGE_SIZE)

    async def test_empty_filters_list_everything(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": [_raw(1), _raw(2)]}
        devices = await _service(client).search_devices(_filters())
        self.assertEqual(len(devices), 2)
        self.assertEqual(set(client.request.await_args.kwargs["params"]), {"offset", "limit"})

    async def test_cidr_uses_prefix_prefilter_then_exact_client_check(self) -> None:
        client = AsyncMock()
        client.request.return_value = {
            "response": [
                _raw(1, managementIpAddress="10.10.20.176"),
                _raw(2, managementIpAddress="10.10.20.177"),
                _raw(3, managementIpAddress="10.10.20.178"),
                _raw(4, managementIpAddress=None),
            ]
        }
        devices = await _service(client).search_devices(_filters(cidr="10.10.20.176/31"))
        self.assertEqual([d.id for d in devices], ["uuid-1", "uuid-2"])
        self.assertEqual(
            client.request.await_args.kwargs["params"]["managementIpAddress"], ["10.10.20..*"]
        )

    async def test_cidr_check_applies_across_pages(self) -> None:
        full = [_raw(i, managementIpAddress="10.9.9.9") for i in range(DEVICE_PAGE_SIZE)]
        client = AsyncMock()
        client.request.side_effect = [
            {"response": full},
            {"response": [_raw(9001, managementIpAddress="10.10.20.5")]},
        ]
        devices = await _service(client).search_devices(_filters(cidr="10.10.20.0/24"))
        self.assertEqual([d.id for d in devices], ["uuid-9001"])
        self.assertEqual(client.request.await_count, 2)

    async def test_max_devices_exactly_met_is_allowed(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": [_raw(1), _raw(2)]}
        devices = await _service(client).search_devices(_filters(roles=["x"]), max_devices=2)
        self.assertEqual(len(devices), 2)

    async def test_max_devices_exceeded_raises_instead_of_truncating(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": [_raw(1), _raw(2), _raw(3)]}
        with self.assertRaises(CatalystCenterTooManyDevicesError) as ctx:
            await _service(client).search_devices(_filters(roles=["x"]), max_devices=2)
        self.assertEqual(ctx.exception.limit, 2)
        self.assertIn("2", str(ctx.exception))

    async def test_too_many_is_a_validation_error(self) -> None:
        self.assertTrue(
            issubclass(CatalystCenterTooManyDevicesError, CatalystCenterValidationError)
        )

    async def test_stops_fetching_once_cap_is_exceeded(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": [_raw(i) for i in range(DEVICE_PAGE_SIZE)]}
        with self.assertRaises(CatalystCenterTooManyDevicesError):
            await _service(client).search_devices(_filters(roles=["x"]), max_devices=10)
        self.assertEqual(client.request.await_count, 1)

    async def test_invalid_max_devices_is_rejected(self) -> None:
        client = AsyncMock()
        for bad in (0, -1, True):
            with self.assertRaises(CatalystCenterValidationError):
                await _service(client).search_devices(_filters(), max_devices=bad)  # type: ignore[arg-type]
        client.request.assert_not_called()


class PreviewDevicesTests(unittest.IsolatedAsyncioTestCase):
    async def test_truncated_when_more_than_limit(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": [_raw(i) for i in range(1, 6)]}
        devices, truncated = await _service(client).preview_devices(_filters(roles=["x"]), limit=3)
        self.assertEqual([d.id for d in devices], ["uuid-1", "uuid-2", "uuid-3"])
        self.assertTrue(truncated)

    async def test_not_truncated_at_or_below_limit(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": [_raw(1), _raw(2), _raw(3)]}
        devices, truncated = await _service(client).preview_devices(_filters(roles=["x"]), limit=3)
        self.assertEqual(len(devices), 3)
        self.assertFalse(truncated)

    async def test_preview_applies_cidr_filter(self) -> None:
        client = AsyncMock()
        client.request.return_value = {
            "response": [
                _raw(1, managementIpAddress="10.10.20.5"),
                _raw(2, managementIpAddress="10.10.99.5"),
            ]
        }
        devices, truncated = await _service(client).preview_devices(
            _filters(cidr="10.10.20.0/24"), limit=5
        )
        self.assertEqual([d.id for d in devices], ["uuid-1"])
        self.assertFalse(truncated)

    async def test_invalid_limit_rejected(self) -> None:
        client = AsyncMock()
        with self.assertRaises(CatalystCenterValidationError):
            await _service(client).preview_devices(_filters(), limit=0)


class SiteSearchTests(unittest.IsolatedAsyncioTestCase):
    """A site selection resolves to member device ids, then to devices (two paths)."""

    @staticmethod
    def _service_with_sites(client: AsyncMock, site_ids) -> CatalystCenterDeviceService:
        service = _service(client)
        service._sites = MagicMock()
        service._sites.device_ids_for_sites = AsyncMock(return_value=frozenset(site_ids))
        return service

    async def test_site_only_fetches_member_devices_by_id(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": [_raw(1), _raw(2)]}
        service = self._service_with_sites(client, {"uuid-1", "uuid-2"})

        devices = await service.search_devices(_filters(sites=["Global/EMEA"]))

        self.assertEqual([d.id for d in devices], ["uuid-1", "uuid-2"])
        params = client.request.await_args.kwargs["params"]
        self.assertEqual(params, {"id": "uuid-1,uuid-2"})
        service._sites.device_ids_for_sites.assert_awaited_once_with(
            ("Global/EMEA",), include_children=True
        )

    async def test_child_site_flag_is_passed_through(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": []}
        service = self._service_with_sites(client, {"uuid-1"})
        await service.search_devices(_filters(sites=["Global"], include_child_sites=False))
        service._sites.device_ids_for_sites.assert_awaited_once_with(
            ("Global",), include_children=False
        )

    async def test_empty_site_never_queries_the_device_list(self) -> None:
        # an empty id list would make the controller return EVERY device
        client = AsyncMock()
        service = self._service_with_sites(client, set())
        self.assertEqual(await service.search_devices(_filters(sites=["Global/Empty"])), ())
        client.request.assert_not_awaited()

    async def test_member_ids_are_fetched_in_chunks(self) -> None:
        ids = [f"uuid-{i}" for i in range(120)]
        client = AsyncMock()
        client.request.side_effect = lambda *a, **k: {"response": []}
        service = self._service_with_sites(client, ids)
        await service.search_devices(_filters(sites=["Global"]))
        sent = [c.kwargs["params"]["id"].split(",") for c in client.request.await_args_list]
        self.assertEqual([len(chunk) for chunk in sent], [50, 50, 20])
        self.assertEqual(sorted(i for chunk in sent for i in chunk), sorted(ids))

    async def test_site_plus_server_filters_intersects_client_side(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": [_raw(1), _raw(2), _raw(3)]}
        service = self._service_with_sites(client, {"uuid-2"})

        devices = await service.search_devices(_filters(sites=["Global"], roles=["ACCESS"]))

        self.assertEqual([d.id for d in devices], ["uuid-2"])
        params = client.request.await_args.kwargs["params"]
        self.assertEqual(params["role"], ["ACCESS"])
        self.assertNotIn("id", params)  # never rely on how the controller combines id + filters

    async def test_site_plus_cidr_uses_prefilter_and_both_checks(self) -> None:
        client = AsyncMock()
        client.request.return_value = {
            "response": [
                _raw(1, managementIpAddress="10.10.20.5"),
                _raw(2, managementIpAddress="10.10.20.6"),
                _raw(3, managementIpAddress="10.10.99.6"),
            ]
        }
        service = self._service_with_sites(client, {"uuid-1", "uuid-3"})
        devices = await service.search_devices(_filters(sites=["Global"], cidr="10.10.20.0/24"))
        self.assertEqual([d.id for d in devices], ["uuid-1"])

    async def test_site_only_with_unprefilterable_cidr_still_checks_cidr(self) -> None:
        client = AsyncMock()
        client.request.return_value = {
            "response": [
                _raw(1, managementIpAddress="10.10.20.5"),
                _raw(2, managementIpAddress="200.1.1.1"),
            ]
        }
        service = self._service_with_sites(client, {"uuid-1", "uuid-2"})
        devices = await service.search_devices(_filters(sites=["Global"], cidr="0.0.0.0/1"))
        self.assertEqual([d.id for d in devices], ["uuid-1"])

    async def test_max_devices_applies_to_site_results(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": [_raw(1), _raw(2), _raw(3)]}
        service = self._service_with_sites(client, {"uuid-1", "uuid-2", "uuid-3"})
        with self.assertRaises(CatalystCenterTooManyDevicesError):
            await service.search_devices(_filters(sites=["Global"]), max_devices=2)

    async def test_preview_with_sites(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": [_raw(1), _raw(2), _raw(3)]}
        service = self._service_with_sites(client, {"uuid-1", "uuid-2", "uuid-3"})
        devices, truncated = await service.preview_devices(_filters(sites=["Global"]), limit=2)
        self.assertEqual(len(devices), 2)
        self.assertTrue(truncated)

    async def test_unknown_site_error_propagates(self) -> None:
        client = AsyncMock()
        service = _service(client)
        service._sites = MagicMock()
        service._sites.device_ids_for_sites = AsyncMock(
            side_effect=CatalystCenterValidationError("Unknown site 'x'")
        )
        with self.assertRaisesRegex(CatalystCenterValidationError, "Unknown site"):
            await service.search_devices(_filters(sites=["x"]))
        client.request.assert_not_awaited()

    async def test_list_sites_delegates_to_the_site_service(self) -> None:
        service = _service(AsyncMock())
        service._sites = MagicMock()
        service._sites.list_sites = AsyncMock(return_value=("a",))
        self.assertEqual(await service.list_sites(), ("a",))
