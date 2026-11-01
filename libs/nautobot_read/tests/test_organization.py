import pytest

from nautobot_read.client import NautobotError
from nautobot_read.networks import InvalidInputError
from tests.conftest import UUID_BER, UUID_DE, UUID_TX_BER, error_text, run


async def test_list_roles_returns_the_names_for_the_content_type(ctx):
    data = await run(ctx, "list_roles", content_type="dcim.device")
    assert [i["name"] for i in data["items"]] == ["Network", "Server"]
    assert data["applied_filters"] == {"content_type": "dcim.device"}


async def test_list_location_types_includes_the_hierarchy(ctx):
    data = await run(ctx, "list_location_types")
    city = next(i for i in data["items"] if i["name"] == "City")
    assert city["parent"] == "Country"


async def test_list_locations_resolves_names_and_sends_canonical_filters(ctx, nautobot):
    nautobot.list_rows["locations"] = [
        {"id": UUID_BER, "name": "Berlin", "description": "HQ", "location_type": {"name": "City"},
         "parent": {"id": UUID_DE, "name": "Germany"}, "status": {"name": "Active"},
         "tags": [{"name": "lab"}]}
    ]
    data = await run(
        ctx, "list_locations",
        location_type="city", parent="germany", status="ACTIVE", name_contains="ber",
    )
    call = nautobot.page_calls[-1]
    assert call["root"] == "locations"
    assert call["filters"] == {
        "location_type": ["City"], "parent": [UUID_DE], "status": ["Active"], "name__ic": ["ber"],
    }
    assert (call["limit"], call["offset"]) == (50, 0)
    item = data["items"][0]
    assert item["path"] == "Germany → Berlin"
    assert item["tags"] == ["lab"]
    assert data["returned"] == 1 and data["has_more"] is False
    assert data["applied_filters"]["parent"] == "Germany"


async def test_list_locations_reports_more_pages(ctx, nautobot):
    nautobot.has_more = True
    data = await run(ctx, "list_locations", limit=2, offset=4)
    assert data["has_more"] is True and data["offset"] == 4


async def test_unknown_filter_value_returns_a_guiding_error(ctx, nautobot):
    text = await error_text(ctx, "list_locations", location_type="Contry")
    assert "No location type 'Contry'" in text and "Closest: 'Country'" in text
    assert nautobot.page_calls == []  # nothing was sent to Nautobot


async def test_ambiguous_parent_asks_for_path_or_id(ctx):
    text = await error_text(ctx, "list_locations", parent="Berlin")
    assert "matches 2 locations" in text
    assert UUID_TX_BER in text


@pytest.mark.parametrize(
    ("limit", "offset"), [(0, 0), (500, 0), (-1, 0), (10, -1), (10, 100_001)]
)
async def test_paging_is_bounded(ctx, nautobot, limit, offset):
    with pytest.raises(InvalidInputError):
        await run(ctx, "list_locations", limit=limit, offset=offset)
    assert nautobot.page_calls == []


async def test_nautobot_failure_reaches_the_caller_as_the_short_error(ctx, nautobot):
    nautobot.fail_with = NautobotError("Could not reach Nautobot. Check that it is running.")
    assert "Could not reach Nautobot" in await error_text(ctx, "list_locations")


async def test_get_location_resolves_by_path_and_returns_details(ctx, nautobot):
    data = await run(ctx, "get_location", location="Germany → Berlin")
    assert nautobot.graphql_calls[-1][1] == {"id": UUID_BER}
    assert data["name"] == "Berlin" and data["path"] == "Germany → Berlin"
    assert data["children"] == []


async def test_get_location_lists_children_with_id_and_path_and_address_fields(
    ctx, nautobot, monkeypatch
):
    row = {
        **nautobot_row(), "facility": "F1", "physical_address": "Street 1", "time_zone": "CET",
        "latitude": 1.5, "longitude": 2.5,
        "children": [
            {"id": UUID_BER, "name": "Berlin", "location_type": {"name": "City"}},
            {"id": "c2", "name": "Room 2"},
        ],
    }

    async def detail(query, variables=None):
        return {"location": row}

    monkeypatch.setattr(nautobot, "graphql", detail)
    data = await run(ctx, "get_location", location="Germany")
    assert data["children"] == [
        {"id": UUID_BER, "name": "Berlin", "location_type": "City", "path": "Germany → Berlin"},
        # not in the directory: the path is built from the parent's
        {"id": "c2", "name": "Room 2", "location_type": None, "path": "Germany → Room 2"},
    ]
    assert (data["facility"], data["time_zone"], data["latitude"]) == ("F1", "CET", 1.5)


async def test_get_location_without_children_has_an_empty_list(ctx, nautobot, monkeypatch):
    async def detail(query, variables=None):
        return {"location": {**nautobot_row(), "children": None}}

    monkeypatch.setattr(nautobot, "graphql", detail)
    assert (await run(ctx, "get_location", location="Germany"))["children"] == []


async def test_the_children_query_asks_for_the_id(ctx, nautobot):
    await run(ctx, "get_location", location="Germany")
    assert "children { id name" in nautobot.graphql_calls[-1][0]


def nautobot_row():
    return {
        "id": UUID_DE, "name": "Germany", "description": "", "location_type": {"name": "Country"},
        "parent": None, "status": {"name": "Active"}, "tags": [],
    }


async def test_list_locations_validates_status_and_tag_against_their_vocabularies(ctx, nautobot):
    await run(ctx, "list_locations", status="planned", tag="LAB")
    assert nautobot.page_calls[-1]["filters"] == {"status": ["Planned"], "tags": ["lab"]}
    assert "No dcim.location tag 'prod'" in await error_text(ctx, "list_locations", tag="prod")


async def test_list_statuses_and_tags_are_scoped_by_content_type(ctx):
    statuses = await run(ctx, "list_statuses", content_type="dcim.location")
    assert [i["name"] for i in statuses["items"]] == ["Active", "Planned"]
    assert statuses["applied_filters"] == {"content_type": "dcim.location"}
    tags = await run(ctx, "list_tags")
    assert [i["name"] for i in tags["items"]] == ["lab"]


async def test_get_location_deleted_after_caching_is_an_error(ctx, nautobot, monkeypatch):
    async def gone(query, variables=None):
        return {"location": None}

    monkeypatch.setattr(nautobot, "graphql", gone)
    assert "No location with id" in await error_text(ctx, "get_location", location="Germany")
