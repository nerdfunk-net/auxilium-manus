"""``total`` on every list query: free on the last page, one count call otherwise."""

import pytest

from nautobot_read.client import Count, NautobotError
from nautobot_read.queries.common import CONTRADICTION
from tests.conftest import DEVICE_ROW, IP_ROW, PREFIX_ROW, VC_ROW, run

# (query, root, kwargs, row) for every query that pages a Nautobot list.
LISTS = [
    ("list_devices", "devices", {}, DEVICE_ROW),
    ("list_locations", "locations", {}, None),
    ("list_interfaces", "interfaces", {"device": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}, None),
    ("list_ip_addresses", "ip_addresses", {}, IP_ROW),
    ("list_prefixes", "prefixes", {}, PREFIX_ROW),
    ("list_virtual_chassis", "virtual_chassis", {}, VC_ROW),
]
IDS = [name for name, *_ in LISTS]


def _rows(nautobot, root, row):
    if row is not None:
        nautobot.list_rows[root] = [row]


@pytest.mark.parametrize(("query", "root", "kwargs", "row"), LISTS, ids=IDS)
async def test_the_last_page_knows_its_total_without_a_count_request(
    ctx, nautobot, query, root, kwargs, row
):
    _rows(nautobot, root, row)
    nautobot.has_more = False
    data = await run(ctx, query, **kwargs)
    assert data["total"] == data["returned"] and data["total_exact"] is True
    assert nautobot.count_calls == []


@pytest.mark.parametrize(("query", "root", "kwargs", "row"), LISTS, ids=IDS)
async def test_a_page_with_more_asks_for_the_count_with_the_same_filters(
    ctx, nautobot, query, root, kwargs, row
):
    _rows(nautobot, root, row)
    nautobot.has_more = True
    data = await run(ctx, query, **kwargs)
    assert (data["total"], data["total_exact"]) == (137, True)
    assert len(nautobot.count_calls) == 1 and nautobot.count_calls[0][0] == root
    assert nautobot.count_calls[0][1] == nautobot.page_calls[-1]["filters"]
    assert "total_error" not in data


async def test_the_total_of_a_later_last_page_adds_the_offset(ctx, nautobot):
    nautobot.list_rows["devices"] = [DEVICE_ROW]
    data = await run(ctx, "list_devices", offset=40)
    assert data["total"] == 41 and nautobot.count_calls == []


async def test_a_page_past_the_end_is_counted_not_assumed(ctx, nautobot):
    nautobot.list_rows["devices"] = []
    nautobot.count_result = Count(3, exact=True)
    data = await run(ctx, "list_devices", offset=100)
    assert data["items"] == [] and data["total"] == 3
    assert len(nautobot.count_calls) == 1


async def test_an_empty_first_page_is_a_total_of_zero_without_a_count(ctx, nautobot):
    nautobot.list_rows["devices"] = []
    data = await run(ctx, "list_devices")
    assert data["total"] == 0 and nautobot.count_calls == []


async def test_a_capped_count_is_reported_as_a_lower_bound(ctx, nautobot):
    nautobot.has_more = True
    nautobot.count_result = Count(5000, exact=False)
    data = await run(ctx, "list_devices")
    assert (data["total"], data["total_exact"]) == (5000, False)


async def test_a_failing_count_keeps_the_rows_and_says_why_there_is_no_total(ctx, nautobot):
    nautobot.list_rows["devices"] = [DEVICE_ROW]
    nautobot.has_more = True
    nautobot.count_result = NautobotError("Nautobot returned an error (HTTP 500).")
    data = await run(ctx, "list_devices")
    assert data["items"][0]["name"] == "device-1" and data["has_more"] is True
    assert data["total_error"] == "Nautobot returned an error (HTTP 500)."
    assert "total" not in data and "total_exact" not in data


async def test_an_exact_count_below_what_the_page_proves_is_not_shown(ctx, nautobot):
    # has_more means a row exists beyond offset + returned; a count of 1 for a one-row page
    # that has more is a filter that was applied differently, not a total.
    nautobot.list_rows["devices"] = [DEVICE_ROW]
    nautobot.has_more = True
    nautobot.count_result = Count(1, exact=True)
    data = await run(ctx, "list_devices")
    assert data["total_error"] == CONTRADICTION and "total" not in data
    assert data["items"][0]["name"] == "device-1"  # the rows are still returned


async def test_a_count_equal_to_the_proven_minimum_is_accepted(ctx, nautobot):
    nautobot.list_rows["devices"] = [DEVICE_ROW]
    nautobot.has_more = True
    # offset 1 + one row shown + has_more: at least 3 rows exist, so 3 is the smallest honest count.
    nautobot.count_result = Count(3, exact=True)
    data = await run(ctx, "list_devices", offset=1)
    assert data["total"] == 3 and data["total_exact"] is True
    assert "total_error" not in data
    nautobot.count_result = Count(2, exact=True)
    assert (await run(ctx, "list_devices", offset=1))["total_error"] == CONTRADICTION


async def test_a_capped_count_below_the_proven_minimum_is_raised_to_it(ctx, nautobot):
    nautobot.list_rows["devices"] = [DEVICE_ROW]
    nautobot.has_more = True
    nautobot.count_result = Count(5000, exact=False)
    data = await run(ctx, "list_devices", offset=6000)
    assert (data["total"], data["total_exact"]) == (6002, False)
