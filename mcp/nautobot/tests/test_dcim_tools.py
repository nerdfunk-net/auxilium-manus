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


MAC_ROW = {
    "name": "Ethernet0/0", "type": "1000base-t", "enabled": True,
    "mac_address": "AA:BB:CC:00:01:00", "status": {"name": "Active"},
    "ip_addresses": [{"address": "192.168.178.240/24"}],
    "device": {"id": UUID_DEV1, "name": "device-1"},
}


async def test_list_interfaces_by_mac_is_a_read_only_tool_that_explains_documented_versus_learned(
    mcp_client,
):
    tools = {t.name: t for t in (await mcp_client.list_tools()).tools}
    tool = tools["list_interfaces_by_mac"]

    text = " ".join(tool.description.split())  # the docstring is wrapped; compare the words
    assert tool.annotations.read_only_hint
    assert "any notation" in text
    assert "NOT the MAC address table a switch has learned" in text  # documented, not learned
    assert tool.input_schema["required"] == ["mac_address"]


async def test_list_interfaces_by_mac_finds_the_interface_and_its_device(mcp_client, nautobot):
    nautobot.list_rows["interfaces"] = [MAC_ROW]

    data = payload(
        await mcp_client.call_tool(
            "list_interfaces_by_mac", {"mac_address": "aabb.cc00.0100", "limit": 5, "offset": 2}
        )
    )

    call = nautobot.page_calls[-1]
    assert call["root"] == "interfaces"
    assert call["filters"] == {"mac_address": ["AA:BB:CC:00:01:00"]}  # one canonical notation
    assert (call["limit"], call["offset"]) == (5, 2)
    assert data["items"] == [
        {
            "device": "device-1", "device_id": UUID_DEV1, "interface": "Ethernet0/0",
            "mac_address": "AA:BB:CC:00:01:00", "type": "1000base-t", "enabled": True,
            "status": "Active", "ip_addresses": ["192.168.178.240/24"],
        }
    ]
    assert data["applied_filters"] == {"mac_address": "AA:BB:CC:00:01:00"}


async def test_list_interfaces_by_mac_with_no_match_is_an_empty_answer_not_an_error(
    mcp_client, nautobot
):
    nautobot.list_rows["interfaces"] = []

    data = payload(
        await mcp_client.call_tool("list_interfaces_by_mac", {"mac_address": "aabb.cc00.0999"})
    )

    assert data["items"] == [] and data["total"] == 0


async def test_list_interfaces_by_mac_rejects_a_malformed_mac_with_a_message_for_the_model(
    mcp_client, nautobot
):
    result = await mcp_client.call_tool("list_interfaces_by_mac", {"mac_address": "not-a-mac"})

    assert result.is_error and "not a valid MAC address" in result.content[0].text
    assert nautobot.page_calls == []  # nothing was sent to Nautobot
