import json

from tests.conftest import DEVICE_ROW, IP_ROW, PREFIX_ROW, UUID_BER


def payload(result):
    assert not result.is_error, result.content
    return result.structured_content or json.loads(result.content[0].text)


async def test_ipam_tools_are_registered_and_read_only(mcp_client):
    tools = {t.name: t for t in (await mcp_client.list_tools()).tools}
    assert {"list_ip_addresses", "list_prefixes", "list_namespaces"} <= set(tools)
    assert all(t.annotations.read_only_hint for t in tools.values())


async def test_list_ip_addresses_passes_every_argument_to_the_query(mcp_client, nautobot):
    nautobot.list_rows["ip_addresses"] = [IP_ROW]
    nautobot.list_rows["devices"] = [DEVICE_ROW]
    data = payload(
        await mcp_client.call_tool(
            "list_ip_addresses",
            {
                "address": "10.0.0.2", "prefix": "10.0.0.7/24", "device": "device-1",
                "namespace": "BLACK", "role": "network", "status": "active", "tag": "lab",
                "dns_name_contains": "d1", "limit": 9, "offset": 2,
            },
        )
    )
    call = next(c for c in nautobot.page_calls if c["root"] == "ip_addresses")
    assert call["filters"] == {
        "address": ["10.0.0.2"], "prefix": ["10.0.0.0/24"], "device": ["device-1"],
        "namespace": ["black"], "role": ["Network"], "status": ["Active"], "tags": ["lab"],
        "dns_name__ic": ["d1"],
    }
    assert (call["limit"], call["offset"]) == (9, 2)
    assert data["items"][0]["assigned_to"] == [{"device": "device-1", "interface": "eth0"}]


async def test_list_prefixes_passes_every_argument_to_the_query(mcp_client, nautobot):
    nautobot.list_rows["prefixes"] = [PREFIX_ROW]
    data = payload(
        await mcp_client.call_tool(
            "list_prefixes",
            {
                "prefix": "10.0.0.0/24", "within": "10.0.0.0/8", "contains": "10.0.0.2",
                "location": "germany → berlin", "namespace": "black", "role": "network",
                "status": "active", "tag": "lab", "limit": 4, "offset": 1,
            },
        )
    )
    call = nautobot.page_calls[-1]
    assert call["filters"] == {
        "prefix": ["10.0.0.0/24"], "within_include": ["10.0.0.0/8"], "contains": ["10.0.0.2"],
        "location": [UUID_BER], "namespace": ["black"], "role": ["Network"],
        "status": ["Active"], "tags": ["lab"],
    }
    assert (call["limit"], call["offset"]) == (4, 1)
    assert data["items"][0]["vlan"] == "10 mgmt"


async def test_invalid_network_input_is_a_tool_error_and_nothing_is_sent(mcp_client, nautobot):
    result = await mcp_client.call_tool("list_prefixes", {"contains": "zzz"})
    assert result.is_error and "'zzz' is not a valid" in result.content[0].text
    assert nautobot.page_calls == []


async def test_list_namespaces(mcp_client):
    data = payload(await mcp_client.call_tool("list_namespaces", {}))
    assert [i["name"] for i in data["items"]] == ["Global", "black"]
