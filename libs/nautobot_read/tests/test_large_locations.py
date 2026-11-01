"""A Nautobot with too many locations to hold as a tree must still answer device questions."""

import pytest

from nautobot_read.client import NautobotError, TooManyRowsError
from nautobot_read.networks import InvalidInputError
from tests.conftest import (
    DEVICE_ROW,
    LOCATION_ROWS,
    PREFIX_ROW,
    UUID_BER,
    UUID_DE,
    UUID_TX_BER,
    error_text,
    run,
)


@pytest.fixture
def big(nautobot):
    nautobot.too_many_locations = True
    nautobot.list_rows["devices"] = [DEVICE_ROW]
    return nautobot


def lookup_call(nautobot):
    return next(c for c in nautobot.page_calls if c["root"] == "locations")


async def test_list_all_failure_is_a_distinct_error_type_with_the_same_message():
    assert issubclass(TooManyRowsError, NautobotError)


async def test_devices_are_listed_without_the_directory_and_show_the_plain_location(ctx, big):
    data = await run(ctx, "list_devices")

    assert data["items"][0]["name"] == "device-1"
    assert data["items"][0]["location"] == "Berlin"
    assert [c["root"] for c in big.page_calls] == ["devices"]


async def test_a_location_name_is_looked_up_directly(ctx, big):
    big.list_rows["locations"] = [LOCATION_ROWS[0]]

    data = await run(ctx, "list_devices", location="Germany")

    assert lookup_call(big)["filters"] == {"name": ["Germany"]}
    device_call = next(c for c in big.page_calls if c["root"] == "devices")
    assert device_call["filters"] == {"location": [UUID_DE]}
    assert data["applied_filters"]["location"] == "Germany"


async def test_a_location_id_needs_no_lookup(ctx, big):
    await run(ctx, "list_devices", location=UUID_BER.upper())

    assert [c["root"] for c in big.page_calls] == ["devices"]
    assert big.page_calls[0]["filters"] == {"location": [UUID_BER]}


async def test_an_ambiguous_location_name_lists_the_candidates_with_ids(ctx, big):
    big.list_rows["locations"] = [LOCATION_ROWS[1], LOCATION_ROWS[2]]

    text = await error_text(ctx, "list_devices", location="Berlin")

    assert "'Berlin' matches 2 locations" in text
    assert UUID_BER in text and UUID_TX_BER in text and "under Texas" in text
    assert "Retry with the id" in text


async def test_an_unknown_location_name_points_to_the_search(ctx, big):
    big.list_rows["locations"] = []

    text = await error_text(ctx, "list_devices", location="Nowhere")

    assert "No location 'Nowhere'" in text and "list_locations" in text


async def test_a_path_cannot_be_resolved_without_the_directory(ctx, big):
    with pytest.raises(InvalidInputError, match="too many locations"):
        await run(ctx, "list_devices", location="Germany → Berlin")
    assert big.page_calls == []


async def test_list_locations_shows_plain_names_and_resolves_the_parent_directly(ctx, big):
    big.list_rows["locations"] = [LOCATION_ROWS[0]]

    data = await run(ctx, "list_locations", parent="Germany")

    assert data["items"][0]["path"] == "Germany"
    assert lookup_call(big)["filters"] == {"name": ["Germany"]}


async def test_get_location_by_name_works_and_children_get_plain_paths(ctx, big, monkeypatch):
    big.list_rows["locations"] = [LOCATION_ROWS[1]]

    async def detail(query, variables=None):
        return {
            "location": {
                **LOCATION_ROWS[1],
                "children": [{"id": "c1", "name": "Room", "location_type": {"name": "Room"}}],
            }
        }

    monkeypatch.setattr(big, "graphql", detail)
    data = await run(ctx, "get_location", location="Berlin")

    assert data["path"] == "Berlin"
    assert data["children"] == [
        {"id": "c1", "name": "Room", "location_type": "Room", "path": "Berlin → Room"}
    ]


async def test_prefixes_by_location_work_too(ctx, big):
    big.list_rows["locations"] = [LOCATION_ROWS[1]]
    big.list_rows["prefixes"] = [PREFIX_ROW]

    data = await run(ctx, "list_prefixes", location="Berlin")

    assert next(c for c in big.page_calls if c["root"] == "prefixes")["filters"] == {
        "location": [UUID_BER]
    }
    assert data["applied_filters"]["location"] == "Berlin"


async def test_other_failures_while_loading_the_tree_still_propagate(ctx, nautobot, monkeypatch):
    # Only the tree load fails; the device page would work. Swallowing this would hide an outage
    # behind a half answer (plain location names).
    async def down(*_a, **_k):
        raise NautobotError("Could not reach Nautobot. Check that it is running.")

    monkeypatch.setattr(nautobot, "list_all", down)
    nautobot.list_rows["devices"] = [DEVICE_ROW]

    assert "Could not reach Nautobot" in await error_text(ctx, "list_devices")
