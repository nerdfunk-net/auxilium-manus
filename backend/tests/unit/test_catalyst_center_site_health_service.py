"""CatalystCenterSiteHealthService: GET /site-health normalization, paging, errors."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from services.catalyst_center.common.exceptions import (
    CatalystCenterNotFoundError,
    CatalystCenterValidationError,
)
from services.catalyst_center.credentials import CatalystCenterCredentials
from services.catalyst_center.site_health_service import (
    PAGE_SIZE,
    SITE_HEALTH_PATH,
    CatalystCenterSiteHealthService,
)


def _service(responder) -> tuple[CatalystCenterSiteHealthService, list]:
    calls: list = []
    client = AsyncMock()

    async def request(creds, method, path, *, params=None, json=None):
        calls.append((path, params))
        return responder(params)

    client.request = request
    creds = CatalystCenterCredentials("https://dnac", "admin", "pw")
    return CatalystCenterSiteHealthService(client, creds), calls


def _run(service, **kwargs):
    return asyncio.run(service.list_site_health(**kwargs))


def test_rows_are_normalized_and_numbers_coerced() -> None:
    row = {
        "siteName": "Berlin",
        "siteType": "building",
        "parentSiteName": "EMEA",
        "networkHealthAverage": "87",
        "numberOfNetworkDevice": "12",
        "networkHealthAccess": 90,
        "networkHealthCore": None,
        "numberOfClients": 40,
        "clientHealthWired": "100",
        "ignored": "x",
    }
    service, calls = _service(lambda p: {"response": [row, {"siteName": ""}, "junk"]})

    rows = _run(service)

    assert len(rows) == 1
    assert rows[0].site_name == "Berlin" and rows[0].site_type == "building"
    assert rows[0].network_health_average == 87.0 and rows[0].number_of_network_devices == 12
    assert rows[0].health_core is None and rows[0].client_health_wired == 100.0
    assert calls[0][0] == SITE_HEALTH_PATH and "siteType" not in calls[0][1]


def test_site_type_is_sent_and_validated() -> None:
    service, calls = _service(lambda p: {"response": []})

    _run(service, site_type="BUILDING")

    assert calls[0][1]["siteType"] == "BUILDING"
    for bad in ("CAMPUS", "FLOOR"):  # floors are not in /site-health
        with pytest.raises(CatalystCenterValidationError):
            _run(service, site_type=bad)


def test_paging_continues_until_a_short_page() -> None:
    def responder(params):
        n = PAGE_SIZE if params["offset"] == 1 else 2
        return {"response": [{"siteName": f"s{params['offset']}-{i}"} for i in range(n)]}

    service, calls = _service(responder)

    assert len(_run(service)) == PAGE_SIZE + 2
    assert [c[1]["offset"] for c in calls] == [1, 1 + PAGE_SIZE]


def test_unexpected_body_is_a_validation_error_and_404_passes_through() -> None:
    with pytest.raises(CatalystCenterValidationError):
        _run(_service(lambda p: {"response": "boom"})[0])

    client = AsyncMock()
    client.request = AsyncMock(side_effect=CatalystCenterNotFoundError("nope"))
    creds = CatalystCenterCredentials("https://dnac", "admin", "pw")
    with pytest.raises(CatalystCenterNotFoundError):
        _run(CatalystCenterSiteHealthService(client, creds))


def test_page_size_is_the_documented_maximum() -> None:
    service, calls = _service(lambda p: {"response": []})

    _run(service)

    assert PAGE_SIZE == 50 and calls[0][1]["limit"] == 50


def test_non_finite_and_fractional_numbers_do_not_fail_the_list() -> None:
    row = {
        "siteName": "Berlin",
        "networkHealthAverage": "NaN",
        "numberOfNetworkDevice": "Infinity",
        "numberOfClients": "12.9",
        "clientHealthWired": float("inf"),
    }
    other = {"siteName": "Bonn", "networkHealthAverage": 50, "numberOfClients": 7}
    service, _ = _service(lambda p: {"response": [row, other]})

    berlin, bonn = _run(service)

    assert berlin.network_health_average is None and berlin.number_of_network_devices is None
    assert berlin.number_of_clients is None and berlin.client_health_wired is None
    assert bonn.network_health_average == 50.0 and bonn.number_of_clients == 7


def test_aggregate_rows_are_marked_as_totals_and_switch_ap_wlc_are_mapped() -> None:
    # Shapes seen live on the DevNet sandbox (Catalyst Center 3.723).
    all_sites = {
        "siteName": " All Sites",
        "siteId": "",
        "siteType": "area",
        "networkHealthAverage": 100,
        "numberOfNetworkDevice": 4,
        "networkHealthSwitch": 100,
        "networkHealthAP": None,
        "networkHealthWLC": 80,
    }
    all_buildings = {**all_sites, "siteName": " All Buildings", "siteId": " All Buildings"}
    real = {**all_sites, "siteName": "Berlin", "siteId": "abc-123", "siteType": "building"}
    service, _ = _service(lambda p: {"response": [all_sites, all_buildings, real]})

    totals, buildings, berlin = _run(service)

    assert totals.site_name == "All Sites" and totals.is_total
    assert buildings.is_total and not berlin.is_total
    assert berlin.health_switch == 100.0 and berlin.health_ap is None and berlin.health_wlc == 80.0


def test_a_real_site_row_without_an_id_is_not_a_total() -> None:
    row = {"siteName": "Berlin", "siteType": "building", "networkHealthAverage": 90}
    service, _ = _service(lambda p: {"response": [row]})

    (berlin,) = _run(service)

    assert not berlin.is_total
