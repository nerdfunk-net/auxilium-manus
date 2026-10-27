import json

import pytest

from tests.conftest import DEVICE_ROW, IP_ROW, PREFIX_ROW, UUID_BER, UUID_DEV1, UUID_DEV2


def payload(result):
    assert not result.is_error, result.content
    return result.structured_content or json.loads(result.content[0].text)


async def test_ipam_tools_are_registered_and_read_only(mcp_client):
    tools = {t.name: t for t in (await mcp_client.list_tools()).tools}
    assert {"list_ip_addresses", "list_prefixes", "list_namespaces"} <= set(tools)
    assert all(t.annotations.read_only_hint for t in tools.values())


async def test_list_ip_addresses_resolves_and_normalizes_filters(mcp_client, nautobot):
    nautobot.list_rows["ip_addresses"] = [IP_ROW]
    nautobot.list_rows["devices"] = [DEVICE_ROW]
    data = payload(
        await mcp_client.call_tool(
            "list_ip_addresses",
            {
                "address": "10.0.0.2", "prefix": "10.0.0.7/24", "device": "device-1",
                "namespace": "BLACK", "role": "network", "status": "active", "tag": "lab",
                "dns_name_contains": "d1",
            },
        )
    )
    ip_call = next(c for c in nautobot.page_calls if c["root"] == "ip_addresses")
    assert ip_call["filters"] == {
        "address": ["10.0.0.2"], "prefix": ["10.0.0.0/24"], "device": ["device-1"],
        "namespace": ["black"], "role": ["Network"], "status": ["Active"], "tags": ["lab"],
        "dns_name__ic": ["d1"],
    }
    item = data["items"][0]
    assert item["address"] == "10.0.0.2/24" and item["prefix"] == "10.0.0.0/24"
    assert item["namespace"] == "black" and item["status"] == "Active"
    assert item["assigned_to"] == [{"device": "device-1", "interface": "eth0"}]
    assert item["primary_ip_for"] == ["device-1"]
    assert data["applied_filters"]["prefix"] == "10.0.0.0/24"


async def test_ip_device_given_as_id_is_translated_to_its_exact_name(mcp_client, nautobot):
    payload(await mcp_client.call_tool("list_ip_addresses", {"device": UUID_DEV1}))
    assert nautobot.graphql_calls[-1][1] == {"id": UUID_DEV1}
    assert nautobot.page_calls[-1]["filters"] == {"device": ["device-1"]}


async def test_ip_device_name_is_canonicalised_from_nautobot(mcp_client, nautobot):
    nautobot.list_rows["devices"] = [{**DEVICE_ROW, "name": "Device-1"}]
    payload(await mcp_client.call_tool("list_ip_addresses", {"device": "device-1"}))
    assert nautobot.page_calls[-1]["filters"] == {"device": ["Device-1"]}


async def test_ip_unknown_device_and_ambiguous_device_fail_clearly(mcp_client, nautobot):
    nautobot.list_rows["devices"] = []
    missing = await mcp_client.call_tool("list_ip_addresses", {"device": "nope"})
    assert missing.is_error and "No device 'nope'" in missing.content[0].text
    nautobot.list_rows["devices"] = [DEVICE_ROW, {**DEVICE_ROW, "id": UUID_DEV2}]
    twice = await mcp_client.call_tool("list_ip_addresses", {"device": "device-1"})
    assert twice.is_error and "matches 2 devices" in twice.content[0].text


@pytest.mark.parametrize(
    ("tool", "argument", "value"),
    [
        ("list_ip_addresses", "address", "999.1.1.1"),
        ("list_ip_addresses", "prefix", "nonsense"),
        ("list_prefixes", "prefix", "10.0.0.0/99"),
        ("list_prefixes", "within", "zzz"),
        ("list_prefixes", "contains", "zzz"),
    ],
)
async def test_invalid_network_input_is_rejected_before_calling_nautobot(
    mcp_client, nautobot, tool, argument, value
):
    # Nautobot silently ignores some invalid values (contains="zzz" returned every prefix).
    result = await mcp_client.call_tool(tool, {argument: value})
    assert result.is_error
    assert f"'{value}' is not a valid" in result.content[0].text
    assert nautobot.page_calls == []


async def test_ipv6_is_accepted(mcp_client, nautobot):
    payload(await mcp_client.call_tool("list_ip_addresses", {"address": "2001:db8::1"}))
    assert nautobot.page_calls[-1]["filters"] == {"address": ["2001:db8::1"]}


async def test_list_prefixes_maps_filters_and_formats_items(mcp_client, nautobot):
    nautobot.list_rows["prefixes"] = [PREFIX_ROW]
    data = payload(
        await mcp_client.call_tool(
            "list_prefixes",
            {
                "within": "10.0.0.0/8", "contains": "10.0.0.2", "location": "germany → berlin",
                "namespace": "black", "role": "network", "status": "active", "tag": "lab",
            },
        )
    )
    call = nautobot.page_calls[-1]
    assert call["root"] == "prefixes"
    assert call["filters"] == {
        "within_include": ["10.0.0.0/8"], "contains": ["10.0.0.2"], "location": [UUID_BER],
        "namespace": ["black"], "role": ["Network"], "status": ["Active"], "tags": ["lab"],
    }
    item = data["items"][0]
    assert item["prefix"] == "10.0.0.0/24" and item["namespace"] == "black"
    assert item["vlan"] == "10 mgmt" and item["locations"] == ["Berlin"]
    assert item["parent"] == "10.0.0.0/16"
    assert data["applied_filters"]["location"] == "Germany → Berlin"


async def test_list_prefixes_exact_prefix_filter(mcp_client, nautobot):
    payload(await mcp_client.call_tool("list_prefixes", {"prefix": "10.0.0.0/24"}))
    assert nautobot.page_calls[-1]["filters"] == {"prefix": ["10.0.0.0/24"]}


async def test_unknown_namespace_lists_the_existing_ones(mcp_client, nautobot):
    result = await mcp_client.call_tool("list_prefixes", {"namespace": "glob"})
    assert result.is_error
    assert "No namespace 'glob'" in result.content[0].text
    assert "Available: Global, black" in result.content[0].text


async def test_list_namespaces(mcp_client):
    data = payload(await mcp_client.call_tool("list_namespaces", {}))
    assert [i["name"] for i in data["items"]] == ["Global", "black"]


async def test_ip_device_id_that_does_not_exist_is_reported(mcp_client, nautobot):
    nautobot.device_detail = None  # graphql answers {"device": None}
    result = await mcp_client.call_tool("list_ip_addresses", {"device": UUID_DEV1})
    assert result.is_error
    assert f"No device with id '{UUID_DEV1}'" in result.content[0].text
    assert nautobot.page_calls == []
