import json

from tests.conftest import UUID_BER, UUID_DE, UUID_TX_BER


def payload(result):
    assert not result.is_error, result.content
    return result.structured_content or json.loads(result.content[0].text)


async def test_server_exposes_read_only_organization_tools(mcp_client):
    tools = {t.name: t for t in (await mcp_client.list_tools()).tools}
    assert {"list_locations", "get_location", "list_location_types", "list_roles",
            "list_statuses", "list_tags"} <= set(tools)
    assert all(t.annotations and t.annotations.read_only_hint for t in tools.values())


async def test_instructions_are_passed_through(mcp_client):
    assert await mcp_client.instructions() == "test instructions"


async def test_list_roles_returns_the_names_for_the_content_type(mcp_client):
    data = payload(await mcp_client.call_tool("list_roles", {"content_type": "dcim.device"}))
    assert [i["name"] for i in data["items"]] == ["Network", "Server"]


async def test_list_location_types_includes_the_hierarchy(mcp_client):
    data = payload(await mcp_client.call_tool("list_location_types", {}))
    city = next(i for i in data["items"] if i["name"] == "City")
    assert city["parent"] == "Country"


async def test_list_locations_resolves_names_and_sends_canonical_filters(mcp_client, nautobot):
    nautobot.list_rows["locations"] = [
        {"id": UUID_BER, "name": "Berlin", "description": "HQ", "location_type": {"name": "City"},
         "parent": {"id": UUID_DE, "name": "Germany"}, "status": {"name": "Active"},
         "tags": [{"name": "lab"}]}
    ]
    data = payload(await mcp_client.call_tool(
        "list_locations",
        {"location_type": "city", "parent": "germany", "status": "ACTIVE", "name_contains": "ber"},
    ))
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


async def test_list_locations_reports_more_pages(mcp_client, nautobot):
    nautobot.has_more = True
    data = payload(await mcp_client.call_tool("list_locations", {"limit": 2, "offset": 4}))
    assert data["has_more"] is True and data["offset"] == 4


async def test_unknown_filter_value_returns_a_guiding_error(mcp_client, nautobot):
    result = await mcp_client.call_tool("list_locations", {"location_type": "Contry"})
    assert result.is_error
    text = result.content[0].text
    assert "No location type 'Contry'" in text and "Closest: 'Country'" in text
    assert nautobot.page_calls == []  # nothing was sent to Nautobot


async def test_ambiguous_parent_asks_for_path_or_id(mcp_client):
    result = await mcp_client.call_tool("list_locations", {"parent": "Berlin"})
    assert result.is_error
    assert "matches 2 locations" in result.content[0].text
    assert UUID_TX_BER in result.content[0].text


async def test_limit_is_bounded(mcp_client):
    assert (await mcp_client.call_tool("list_locations", {"limit": 0})).is_error
    assert (await mcp_client.call_tool("list_locations", {"limit": 500})).is_error


async def test_nautobot_failure_reaches_the_model_as_a_short_error(mcp_client, nautobot):
    from nautobot_mcp.client import NautobotError

    nautobot.fail_with = NautobotError("Could not reach Nautobot. Check that it is running.")
    result = await mcp_client.call_tool("list_locations", {})
    assert result.is_error
    assert "Could not reach Nautobot" in result.content[0].text


async def test_get_location_resolves_by_path_and_returns_details(mcp_client, nautobot):
    data = payload(await mcp_client.call_tool("get_location", {"location": "Germany → Berlin"}))
    assert nautobot.graphql_calls[-1][1] == {"id": UUID_BER}
    assert data["name"] == "Berlin" and data["path"] == "Germany → Berlin"


async def test_list_locations_validates_status_and_tag_against_their_vocabularies(
    mcp_client, nautobot
):
    payload(await mcp_client.call_tool("list_locations", {"status": "planned", "tag": "LAB"}))
    filters = nautobot.page_calls[-1]["filters"]
    assert filters == {"status": ["Planned"], "tags": ["lab"]}
    bad = await mcp_client.call_tool("list_locations", {"tag": "prod"})
    assert bad.is_error and "No dcim.location tag 'prod'" in bad.content[0].text


async def test_list_statuses_and_tags_are_scoped_by_content_type(mcp_client):
    statuses = payload(
        await mcp_client.call_tool("list_statuses", {"content_type": "dcim.location"})
    )
    assert [i["name"] for i in statuses["items"]] == ["Active", "Planned"]
    assert statuses["applied_filters"] == {"content_type": "dcim.location"}
    tags = payload(await mcp_client.call_tool("list_tags", {}))
    assert [i["name"] for i in tags["items"]] == ["lab"]
    assert (await mcp_client.call_tool("list_tags", {"content_type": "nope"})).is_error


async def test_get_location_deleted_after_caching_is_a_tool_error(
    mcp_client, nautobot, monkeypatch
):
    async def gone(query, variables=None):
        return {"location": None}

    monkeypatch.setattr(nautobot, "graphql", gone)
    result = await mcp_client.call_tool("get_location", {"location": "Germany"})
    assert result.is_error and "No location with id" in result.content[0].text
