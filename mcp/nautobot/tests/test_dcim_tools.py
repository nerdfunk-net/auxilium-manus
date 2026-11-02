import json

from tests.conftest import DEVICE_ROW, UUID_DE, UUID_DEV1, VC_ROW


def payload(result):
    assert not result.is_error, result.content
    return result.structured_content or json.loads(result.content[0].text)


async def test_dcim_tools_are_registered_and_read_only(mcp_client):
    tools = {t.name: t for t in (await mcp_client.list_tools()).tools}
    assert {"list_devices", "get_device", "list_device_types", "list_platforms"} <= set(tools)
    assert all(t.annotations.read_only_hint for t in tools.values())


async def test_list_devices_by_location_keeps_the_children_semantics_in_the_description(
    mcp_client,
):
    tool = next(t for t in (await mcp_client.list_tools()).tools if t.name == "list_devices")
    assert "child locations" in tool.description


async def test_list_devices_passes_every_argument_to_the_query(mcp_client, nautobot):
    nautobot.list_rows["devices"] = [DEVICE_ROW]
    data = payload(
        await mcp_client.call_tool(
            "list_devices",
            {
                "location": "germany", "role": "network", "status": "active", "tag": "LAB",
                "device_type": "NETWORKA", "platform": "cisco ios", "name_contains": "dev",
                "limit": 5, "offset": 10,
            },
        )
    )
    call = nautobot.page_calls[-1]
    assert call["filters"] == {
        "location": [UUID_DE], "role": ["Network"], "status": ["Active"], "tags": ["lab"],
        "device_type": ["networkA"], "platform": ["Cisco IOS"], "name__ic": ["dev"],
    }
    assert (call["limit"], call["offset"]) == (5, 10)
    assert data["items"][0]["name"] == "device-1"


async def test_unknown_role_is_a_tool_error_that_explains_what_exists(mcp_client, nautobot):
    result = await mcp_client.call_tool("list_devices", {"role": "router"})
    assert result.is_error and "Available: Network, Server" in result.content[0].text
    assert nautobot.page_calls == []


async def test_get_device_and_vocabulary_tools(mcp_client, nautobot):
    data = payload(await mcp_client.call_tool("get_device", {"device": UUID_DEV1}))
    assert data["name"] == "device-1" and data["interfaces"][0]["name"] == "eth0"
    missing = await mcp_client.call_tool("get_device", {"device": "nope"})
    assert missing.is_error and "No device 'nope'" in missing.content[0].text
    types = payload(await mcp_client.call_tool("list_device_types", {}))
    assert types["items"][0] == {"model": "networkA", "manufacturer": "NetworkInc"}
    platforms = payload(await mcp_client.call_tool("list_platforms", {}))
    assert platforms["items"][0]["network_driver"] == "cisco_ios"


async def test_virtual_chassis_tools_list_and_get_a_stack(mcp_client, nautobot):
    nautobot.list_rows["virtual_chassis"] = [VC_ROW]
    listed = payload(
        await mcp_client.call_tool("list_virtual_chassis", {"name_contains": "lab", "limit": 5})
    )
    assert nautobot.page_calls[-1]["filters"] == {"name__ic": ["lab"]}
    assert listed["items"][0]["members"] == ["LAB.local.zz"]
    one = payload(
        await mcp_client.call_tool("get_virtual_chassis", {"virtual_chassis": "lab.local.zz"})
    )
    assert one["members"][0]["is_master"] is True
    missing = await mcp_client.call_tool("get_virtual_chassis", {"virtual_chassis": "nope"})
    assert missing.is_error and "No virtual chassis 'nope'" in missing.content[0].text


async def test_a_list_with_more_pages_reports_the_total(mcp_client, nautobot):
    nautobot.list_rows["devices"] = [DEVICE_ROW]
    nautobot.has_more = True
    data = payload(await mcp_client.call_tool("list_devices", {"tag": "LAB", "limit": 1}))
    assert (data["total"], data["total_exact"]) == (42, True)
    assert nautobot.count_calls == [("devices", {"tags": ["lab"]})]
