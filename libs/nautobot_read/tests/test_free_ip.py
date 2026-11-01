import ipaddress

import pytest

from nautobot_read.client import GraphQLClient, NautobotError
from nautobot_read.networks import InvalidInputError
from tests.conftest import UUID_PFX, UUID_PFX_BLACK, UUID_PFX_WIDE, error_text, run

GLOBAL = {"id": UUID_PFX, "prefix": "10.0.0.0/24", "namespace": {"name": "Global"}}
BLACK = {"id": UUID_PFX_BLACK, "prefix": "10.0.0.0/24", "namespace": {"name": "black"}}
WIDE = {"id": UUID_PFX_WIDE, "prefix": "10.0.0.0/8", "namespace": {"name": "Global"}}


def prefix_call(nautobot):
    return next(c for c in nautobot.page_calls if c["root"] == "prefixes")


async def test_returns_the_next_free_address_after_the_network_address(ctx, nautobot):
    nautobot.list_rows["prefixes"] = [GLOBAL]

    data = await run(ctx, "get_next_free_ip", prefix="10.0.0.0/24")

    assert data["addresses"] == ["10.0.0.1"]
    assert (data["prefix"], data["namespace"], data["start_offset"]) == (
        "10.0.0.0/24", "Global", 1,
    )
    assert (data["requested"], data["returned"], data["complete"]) == (1, 1, True)
    assert "nothing is reserved" in data["note"].lower()
    assert prefix_call(nautobot)["filters"] == {"prefix": ["10.0.0.0/24"]}


async def test_asks_nautobot_for_just_enough_addresses(ctx, nautobot):
    nautobot.list_rows["prefixes"] = [GLOBAL]

    await run(ctx, "get_next_free_ip", prefix="10.0.0.0/24", count=3, start_offset=5)

    assert nautobot.rest_calls == [
        f"ipam/prefixes/{UUID_PFX}/available-ips/?limit=8&format=json"
    ]


async def test_count_and_start_offset_pick_the_addresses(ctx, nautobot):
    nautobot.list_rows["prefixes"] = [GLOBAL]

    data = await run(ctx, "get_next_free_ip", prefix="10.0.0.0/24", count=3, start_offset=5)

    assert data["addresses"] == ["10.0.0.5", "10.0.0.6", "10.0.0.7"]


async def test_host_bits_are_cleared_like_the_workflow_step(ctx, nautobot):
    nautobot.list_rows["prefixes"] = [GLOBAL]

    await run(ctx, "get_next_free_ip", prefix="10.0.0.77/24")

    assert prefix_call(nautobot)["filters"] == {"prefix": ["10.0.0.0/24"]}


async def test_the_namespace_is_resolved_against_its_vocabulary(ctx, nautobot):
    nautobot.list_rows["prefixes"] = [BLACK]

    data = await run(ctx, "get_next_free_ip", prefix="10.0.0.0/24", namespace="BLACK")

    assert prefix_call(nautobot)["filters"] == {"prefix": ["10.0.0.0/24"], "namespace": ["black"]}
    assert data["namespace"] == "black"


async def test_an_unknown_namespace_lists_the_existing_ones(ctx, nautobot):
    text = await error_text(ctx, "get_next_free_ip", prefix="10.0.0.0/24", namespace="glob")

    assert "No namespace 'glob'" in text and "Available: Global, black" in text
    assert nautobot.page_calls == [] and nautobot.rest_calls == []


async def test_a_prefix_in_several_namespaces_asks_which_one(ctx, nautobot):
    nautobot.list_rows["prefixes"] = [GLOBAL, BLACK]

    text = await error_text(ctx, "get_next_free_ip", prefix="10.0.0.0/24")

    assert "exists in 2 namespaces: Global, black" in text and "namespace" in text
    assert nautobot.rest_calls == []


async def test_a_missing_prefix_says_so(ctx, nautobot):
    nautobot.list_rows["prefixes"] = []

    text = await error_text(ctx, "get_next_free_ip", prefix="10.9.9.0/24")
    assert "No prefix 10.9.9.0/24 in Nautobot" in text and "list_prefixes" in text
    named = await error_text(ctx, "get_next_free_ip", prefix="10.9.9.0/24", namespace="black")
    assert "in namespace 'black'" in named


async def test_a_bare_address_uses_the_most_specific_containing_prefix(ctx, nautobot):
    nautobot.list_rows["prefixes"] = [WIDE, GLOBAL]

    data = await run(ctx, "get_next_free_ip", prefix="10.0.0.9")

    assert prefix_call(nautobot)["filters"] == {"contains": ["10.0.0.9"]}
    assert data["prefix"] == "10.0.0.0/24"
    assert nautobot.rest_calls[0].startswith(f"ipam/prefixes/{UUID_PFX}/")


async def test_a_bare_address_in_two_namespaces_asks_which_one(ctx, nautobot):
    nautobot.list_rows["prefixes"] = [GLOBAL, BLACK]

    assert "2 namespaces" in await error_text(ctx, "get_next_free_ip", prefix="10.0.0.9")


async def test_a_bare_address_with_nothing_containing_it(ctx, nautobot):
    nautobot.list_rows["prefixes"] = []

    assert "No prefix contains 10.0.0.9 in Nautobot" in await error_text(
        ctx, "get_next_free_ip", prefix="10.0.0.9"
    )


async def test_too_many_containing_prefixes_asks_for_a_cidr(ctx, nautobot):
    nautobot.list_rows["prefixes"] = [GLOBAL]
    nautobot.has_more = True

    assert "More than 200 prefixes contain" in await error_text(
        ctx, "get_next_free_ip", prefix="10.0.0.9"
    )


async def test_a_row_for_another_prefix_is_not_used(ctx, nautobot):
    # Defensive: Nautobot's exact filter should not return it, but a wrong prefix must not
    # hand out addresses.
    nautobot.list_rows["prefixes"] = [WIDE]

    assert "No prefix 10.0.0.0/24" in await error_text(
        ctx, "get_next_free_ip", prefix="10.0.0.0/24"
    )


async def test_fewer_free_addresses_than_requested_is_reported_not_raised(ctx, nautobot):
    nautobot.list_rows["prefixes"] = [GLOBAL]
    nautobot.available = [{"address": "10.0.0.8/24"}, {"address": "10.0.0.9/24"}]

    data = await run(ctx, "get_next_free_ip", prefix="10.0.0.0/24", count=5)

    assert data["addresses"] == ["10.0.0.8", "10.0.0.9"]
    assert (data["returned"], data["complete"]) == (2, False)
    assert "Only 2 free address" in data["note"] and "is full from there" in data["note"]


async def test_a_full_prefix_returns_nothing_and_says_so(ctx, nautobot):
    nautobot.list_rows["prefixes"] = [GLOBAL]
    nautobot.available = []

    data = await run(ctx, "get_next_free_ip", prefix="10.0.0.0/24")

    assert data["addresses"] == [] and data["complete"] is False


async def test_a_large_offset_that_exceeds_the_read_window_is_flagged(ctx, nautobot):
    # Nautobot lists free addresses from the start of the prefix and is asked for at most 1000:
    # an offset of 1000 cannot be reached, which is not proof that the prefix is full.
    base = int(ipaddress.ip_address("10.0.0.0"))
    nautobot.available = [{"address": f"{ipaddress.ip_address(base + n)}/16"} for n in range(1000)]
    nautobot.list_rows["prefixes"] = [{**GLOBAL, "prefix": "10.0.0.0/16"}]

    data = await run(ctx, "get_next_free_ip", prefix="10.0.0.0/16", start_offset=1000)

    assert nautobot.rest_calls[0].endswith("limit=1000&format=json")
    assert data["addresses"] == [] and data["complete"] is False
    assert "first 1000 free addresses" in data["note"]
    assert "is full from there" not in data["note"]


async def test_exactly_the_window_is_not_flagged_as_cut(ctx, nautobot):
    nautobot.list_rows["prefixes"] = [{**GLOBAL, "prefix": "10.0.0.0/16"}]
    nautobot.available = [{"address": "10.0.3.231/16"}]

    data = await run(ctx, "get_next_free_ip", prefix="10.0.0.0/16", start_offset=999)

    assert data["addresses"] == ["10.0.3.231"] and data["complete"] is True


async def test_entries_outside_the_prefix_or_malformed_are_ignored(ctx, nautobot):
    nautobot.list_rows["prefixes"] = [GLOBAL]
    nautobot.available = [
        "junk", {"address": ""}, {"address": "not-an-ip/24"}, {"address": "192.168.0.7/24"},
        {"address": "2001:db8::1/64"}, {"address": "10.0.0.4/24"},
    ]

    data = await run(ctx, "get_next_free_ip", prefix="10.0.0.0/24")

    assert data["addresses"] == ["10.0.0.4"]


async def test_ipv6_prefix(ctx, nautobot):
    nautobot.list_rows["prefixes"] = [
        {"id": UUID_PFX, "prefix": "2001:db8::/64", "namespace": {"name": "Global"}}
    ]
    nautobot.available = [{"address": "2001:db8::1/64"}, {"address": "2001:db8::2/64"}]

    data = await run(ctx, "get_next_free_ip", prefix="2001:DB8::/64", count=2)

    assert prefix_call(nautobot)["filters"] == {"prefix": ["2001:db8::/64"]}
    assert data["addresses"] == ["2001:db8::1", "2001:db8::2"]


@pytest.mark.parametrize(
    "kwargs",
    [{"count": 0}, {"count": 21}, {"start_offset": -1}, {"start_offset": 1_000_001}],
)
async def test_bounds_are_checked_before_calling_nautobot(ctx, nautobot, kwargs):
    with pytest.raises(InvalidInputError):
        await run(ctx, "get_next_free_ip", prefix="10.0.0.0/24", **kwargs)
    assert nautobot.page_calls == [] and nautobot.rest_calls == []


async def test_an_invalid_prefix_is_rejected_before_calling_nautobot(ctx, nautobot):
    assert "is not a valid" in await error_text(ctx, "get_next_free_ip", prefix="nonsense")
    assert nautobot.page_calls == []


async def test_a_prefix_id_that_is_not_a_uuid_is_never_put_in_the_request_path(ctx, nautobot):
    nautobot.list_rows["prefixes"] = [{**GLOBAL, "id": "../../users"}]

    assert "not a UUID" in await error_text(ctx, "get_next_free_ip", prefix="10.0.0.0/24")
    assert nautobot.rest_calls == []


async def test_an_unexpected_available_ips_body_is_an_error(ctx, nautobot):
    nautobot.list_rows["prefixes"] = [GLOBAL]
    nautobot.available = {"detail": "nope"}

    assert "unexpected" in await error_text(ctx, "get_next_free_ip", prefix="10.0.0.0/24")


async def test_a_nautobot_failure_passes_through(ctx, nautobot):
    nautobot.list_rows["prefixes"] = [GLOBAL]

    async def down(endpoint):
        raise NautobotError("Could not reach Nautobot. Check that it is running.")

    nautobot.rest_get = down
    assert "Could not reach Nautobot" in await error_text(
        ctx, "get_next_free_ip", prefix="10.0.0.0/24"
    )


async def test_a_client_without_rest_support_says_so():
    class GraphqlOnly(GraphQLClient):
        async def graphql(self, query, variables=None):
            return {}

    with pytest.raises(NautobotError, match="REST"):
        await GraphqlOnly().rest_get("ipam/prefixes/")


async def test_a_row_with_an_unreadable_prefix_is_skipped(ctx, nautobot):
    nautobot.list_rows["prefixes"] = [{**WIDE, "prefix": "garbage"}, GLOBAL]

    data = await run(ctx, "get_next_free_ip", prefix="10.0.0.9")

    assert data["prefix"] == "10.0.0.0/24"
