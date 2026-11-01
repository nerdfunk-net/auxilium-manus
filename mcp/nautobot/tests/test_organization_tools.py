import json

from nautobot_read.client import NautobotError

from tests.conftest import UUID_BER, UUID_DE


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


async def test_list_locations_passes_every_argument_to_the_query(mcp_client, nautobot):
    payload(await mcp_client.call_tool(
        "list_locations",
        {"location_type": "city", "parent": "germany", "status": "ACTIVE", "tag": "lab",
         "name_contains": "ber", "limit": 7, "offset": 3},
    ))
    call = nautobot.page_calls[-1]
    assert call["filters"] == {
        "location_type": ["City"], "parent": [UUID_DE], "status": ["Active"], "tags": ["lab"],
        "name__ic": ["ber"],
    }
    assert (call["limit"], call["offset"]) == (7, 3)


async def test_get_location_and_location_types(mcp_client, nautobot):
    data = payload(await mcp_client.call_tool("get_location", {"location": "Germany → Berlin"}))
    assert data["path"] == "Germany → Berlin" and nautobot.graphql_calls[-1][1] == {"id": UUID_BER}
    types = payload(await mcp_client.call_tool("list_location_types", {}))
    assert {i["name"] for i in types["items"]} >= {"Country", "City"}


async def test_vocabulary_tools_take_a_content_type(mcp_client):
    roles = payload(await mcp_client.call_tool("list_roles", {"content_type": "dcim.device"}))
    assert [i["name"] for i in roles["items"]] == ["Network", "Server"]
    statuses = payload(
        await mcp_client.call_tool("list_statuses", {"content_type": "dcim.location"})
    )
    assert statuses["applied_filters"] == {"content_type": "dcim.location"}
    assert [i["name"] for i in payload(await mcp_client.call_tool("list_tags", {}))["items"]] == [
        "lab"
    ]
    assert (await mcp_client.call_tool("list_tags", {"content_type": "nope"})).is_error


async def test_expected_errors_reach_the_model_as_their_own_text(mcp_client, nautobot):
    unknown = await mcp_client.call_tool("list_locations", {"location_type": "Contry"})
    assert unknown.is_error and "Closest: 'Country'" in unknown.content[0].text
    ambiguous = await mcp_client.call_tool("list_locations", {"parent": "Berlin"})
    assert ambiguous.is_error and "matches 2 locations" in ambiguous.content[0].text
    nautobot.fail_with = NautobotError("Could not reach Nautobot. Check that it is running.")
    down = await mcp_client.call_tool("list_locations", {})
    assert down.is_error and "Could not reach Nautobot" in down.content[0].text


async def test_limit_is_bounded_by_the_tool_schema(mcp_client, nautobot):
    assert (await mcp_client.call_tool("list_locations", {"limit": 0})).is_error
    assert (await mcp_client.call_tool("list_locations", {"limit": 500})).is_error
    assert (await mcp_client.call_tool("list_locations", {"offset": 100_001})).is_error
    assert nautobot.page_calls == []
