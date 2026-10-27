import json

from tests.conftest import (
    DEVICE_ROW,
    UUID_BER,
    UUID_DE,
    UUID_DEV1,
    UUID_DEV2,
)


def payload(result):
    assert not result.is_error, result.content
    return result.structured_content or json.loads(result.content[0].text)


async def test_dcim_tools_are_registered_and_read_only(mcp_client):
    tools = {t.name: t for t in (await mcp_client.list_tools()).tools}
    assert {"list_devices", "get_device", "list_device_types", "list_platforms"} <= set(tools)
    assert all(t.annotations.read_only_hint for t in tools.values())


async def test_list_devices_resolves_every_filter_to_a_canonical_value(mcp_client, nautobot):
    nautobot.list_rows["devices"] = [DEVICE_ROW]
    data = payload(
        await mcp_client.call_tool(
            "list_devices",
            {
                "location": "germany", "role": "network", "status": "active", "tag": "LAB",
                "device_type": "NETWORKA", "platform": "cisco ios", "name_contains": "dev",
            },
        )
    )
    call = nautobot.page_calls[-1]
    assert call["root"] == "devices"
    assert call["filters"] == {
        "location": [UUID_DE], "role": ["Network"], "status": ["Active"], "tags": ["lab"],
        "device_type": ["networkA"], "platform": ["Cisco IOS"], "name__ic": ["dev"],
    }
    item = data["items"][0]
    assert item["name"] == "device-1" and item["role"] == "Network"
    assert item["device_type"] == "networkA" and item["manufacturer"] == "NetworkInc"
    assert item["location"] == "Germany → Berlin"
    assert item["primary_ip4"] == "10.0.0.2/24" and item["tags"] == ["lab"]
    assert data["applied_filters"]["location"] == "Germany"
    assert data["applied_filters"]["role"] == "Network"


async def test_list_devices_without_filters_sends_none(mcp_client, nautobot):
    payload(await mcp_client.call_tool("list_devices", {}))
    assert nautobot.page_calls[-1]["filters"] == {}


async def test_list_devices_unknown_role_explains_what_exists(mcp_client, nautobot):
    result = await mcp_client.call_tool("list_devices", {"role": "router"})
    assert result.is_error
    text = result.content[0].text
    assert "No dcim.device role 'router'" in text and "Available: Network, Server" in text
    assert nautobot.page_calls == []


async def test_list_devices_by_location_keeps_the_children_semantics_in_the_description(mcp_client):
    tool = next(t for t in (await mcp_client.list_tools()).tools if t.name == "list_devices")
    assert "child locations" in tool.description


async def test_get_device_by_id_returns_details_with_interfaces(mcp_client, nautobot):
    data = payload(await mcp_client.call_tool("get_device", {"device": UUID_DEV1.upper()}))
    assert nautobot.graphql_calls[-1][1] == {"id": UUID_DEV1}
    assert data["name"] == "device-1" and data["location"] == "Germany → Berlin"
    assert data["interfaces"] == [
        {"name": "eth0", "type": "VIRTUAL", "enabled": True, "mac_address": None,
         "description": "", "status": "Active", "ip_addresses": ["10.0.0.2/24"]},
    ]
    assert data["interfaces_truncated"] is False


async def test_get_device_by_name_looks_the_id_up_first(mcp_client, nautobot):
    nautobot.list_rows["devices"] = [DEVICE_ROW]
    payload(await mcp_client.call_tool("get_device", {"device": "device-1"}))
    assert nautobot.page_calls[0]["filters"] == {"name": ["device-1"]}
    assert nautobot.graphql_calls[-1][1] == {"id": UUID_DEV1}


async def test_get_device_unknown_name_points_to_list_devices(mcp_client, nautobot):
    nautobot.list_rows["devices"] = []
    result = await mcp_client.call_tool("get_device", {"device": "nope"})
    assert result.is_error
    assert "No device 'nope'" in result.content[0].text
    assert "list_devices" in result.content[0].text


async def test_get_device_duplicate_names_are_ambiguous(mcp_client, nautobot):
    other = {**DEVICE_ROW, "id": UUID_DEV2, "location": {"id": UUID_BER, "name": "Texas Site"}}
    nautobot.list_rows["devices"] = [DEVICE_ROW, other]
    result = await mcp_client.call_tool("get_device", {"device": "device-1"})
    assert result.is_error
    text = result.content[0].text
    assert "'device-1' matches 2 devices" in text
    assert UUID_DEV1 in text and UUID_DEV2 in text and "Retry with the id" in text


async def test_get_device_truncates_very_long_interface_lists(mcp_client, nautobot):
    nautobot.list_rows["interfaces"] = [
        {"name": f"e{i}", "type": "1000base-t", "enabled": True, "mac_address": None,
         "description": "", "status": {"name": "Active"}, "ip_addresses": []}
        for i in range(100)
    ]
    nautobot.has_more = True
    data = payload(await mcp_client.call_tool("get_device", {"device": UUID_DEV1}))
    assert len(data["interfaces"]) == 100 and data["interfaces_truncated"] is True
    call = nautobot.page_calls[-1]
    assert call["root"] == "interfaces" and call["limit"] == 100
    assert call["filters"] == {"device_id": [UUID_DEV1]}


async def test_get_device_unknown_id_is_a_tool_error(mcp_client, nautobot):
    nautobot.device_detail = None
    result = await mcp_client.call_tool("get_device", {"device": UUID_DEV1})
    assert result.is_error and f"No device with id '{UUID_DEV1}'" in result.content[0].text


async def test_ambiguous_name_says_when_the_match_list_is_capped(mcp_client, nautobot):
    other = {**DEVICE_ROW, "id": UUID_DEV2}
    nautobot.list_rows["devices"] = [DEVICE_ROW, other]
    nautobot.has_more = True
    result = await mcp_client.call_tool("get_device", {"device": "device-1"})
    text = result.content[0].text
    assert "at least 2 devices" in text and "list truncated" in text


async def test_list_device_types_and_platforms_show_manufacturer(mcp_client):
    types = payload(await mcp_client.call_tool("list_device_types", {}))
    assert types["items"][0] == {"model": "networkA", "manufacturer": "NetworkInc"}
    platforms = payload(await mcp_client.call_tool("list_platforms", {}))
    assert platforms["items"][0] == {
        "name": "Cisco IOS", "manufacturer": None, "network_driver": "cisco_ios",
    }
