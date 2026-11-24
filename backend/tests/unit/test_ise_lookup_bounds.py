"""W6-07: the ISE helpers are bounded and do not repeat work.

* pagination stops at a page cap instead of following `nextPage` forever,
* detail requests run eight at a time by default (they were sequential),
* `get-ise-tacacs-key` lists one location group once, however many devices share the location.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.ise.common.exceptions import ISEAPIError
from tests.unit._step_helpers import make_device
from workflow_steps.common import ise_lookup
from workflow_steps.get_ise_tacacs_key import executor as tacacs


@pytest.mark.asyncio
async def test_an_endless_next_page_is_cut_off_with_a_classified_error() -> None:
    calls = 0

    async def fetch_page(page: int) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"SearchResult": {"resources": [], "nextPage": {"href": "x"}}}

    with patch.object(ise_lookup, "MAX_PAGES", 5):
        with pytest.raises(ISEAPIError) as caught:
            await ise_lookup.paginate_ise_summaries(fetch_page)
    assert calls == 5
    assert caught.value.failure is not None and caught.value.failure.kind == "invalid_response"


@pytest.mark.asyncio
async def test_a_normal_pagination_is_unchanged() -> None:
    async def fetch_page(page: int) -> dict[str, Any]:
        more = {"href": "x"} if page < 3 else None
        return {"SearchResult": {"resources": [{"id": f"p{page}"}], "nextPage": more}}

    summaries = await ise_lookup.paginate_ise_summaries(fetch_page)
    assert [s["id"] for s in summaries] == ["p1", "p2", "p3"]


@pytest.mark.asyncio
async def test_details_are_fetched_in_parallel_by_default_in_summary_order() -> None:
    running = peak = 0

    async def get_device(device_id: str) -> dict[str, Any]:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return {"NetworkDevice": {"id": device_id}}

    service = MagicMock()
    service.get_device = get_device
    summaries = [{"id": f"d{i}"} for i in range(20)]
    details = await ise_lookup.fetch_ise_device_details(service, summaries)
    assert [d["id"] for d in details] == [f"d{i}" for i in range(20)]
    assert 1 < peak <= 8


@pytest.mark.asyncio
async def test_devices_in_one_location_list_the_group_once() -> None:
    service = MagicMock()
    service.list_devices_by_group = AsyncMock(
        return_value={"SearchResult": {"resources": [{"id": "g1"}]}}
    )
    service.get_device = AsyncMock(
        return_value={"NetworkDevice": {"id": "g1", "tacacsSettings": {"sharedSecret": "k"}}}
    )
    groups = tacacs._LocationGroups(service)
    devices = [
        make_device(f"d{i}", attribute_bags={"nautobot": {"location": {"name": "DC1"}}})
        for i in range(3)
    ]
    secrets = [
        await tacacs._tier_location_group(device, service, "Prefix", groups) for device in devices
    ]
    assert secrets == ["k", "k", "k"]
    assert service.list_devices_by_group.await_count == 1
    assert service.get_device.await_count == 1


@pytest.mark.asyncio
async def test_a_failed_group_listing_is_not_cached() -> None:
    service = MagicMock()
    service.list_devices_by_group = AsyncMock(
        side_effect=[ISEAPIError("down"), {"SearchResult": {"resources": []}}]
    )
    groups = tacacs._LocationGroups(service)
    device = make_device("d1", attribute_bags={"nautobot": {"location": {"name": "DC1"}}})
    with pytest.raises(ISEAPIError):
        await tacacs._tier_location_group(device, service, "P", groups)
    assert await tacacs._tier_location_group(device, service, "P", groups) is None
