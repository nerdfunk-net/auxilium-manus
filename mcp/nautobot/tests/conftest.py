from typing import Any

import pytest
from mcp.client import Client

from nautobot_mcp.client import NautobotError, Page
from nautobot_mcp.context import AppContext
from nautobot_mcp.server import build_server
from nautobot_mcp.vocabularies import VocabularyCache

UUID_DE = "11111111-1111-1111-1111-111111111111"
UUID_BER = "22222222-2222-2222-2222-222222222222"
UUID_TX_BER = "33333333-3333-3333-3333-333333333333"
UUID_TX = "44444444-4444-4444-4444-444444444444"

LOCATION_ROWS = [
    {"id": UUID_DE, "name": "Germany", "description": "", "location_type": {"name": "Country"},
     "parent": None, "status": {"name": "Active"}, "tags": []},
    {"id": UUID_BER, "name": "Berlin", "description": "HQ", "location_type": {"name": "City"},
     "parent": {"id": UUID_DE, "name": "Germany"}, "status": {"name": "Active"},
     "tags": [{"name": "lab"}]},
    {"id": UUID_TX_BER, "name": "Berlin", "description": "", "location_type": {"name": "Site"},
     "parent": {"id": UUID_TX, "name": "Texas"}, "status": {"name": "Planned"}, "tags": []},
    {"id": UUID_TX, "name": "Texas", "description": "", "location_type": {"name": "State"},
     "parent": None, "status": {"name": "Active"}, "tags": []},
]
UUID_DEV1 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
UUID_DEV2 = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
DEVICE_ROW = {
    "id": UUID_DEV1, "name": "device-1", "serial": "SN1", "role": {"name": "Network"},
    "status": {"name": "Active"},
    "device_type": {"model": "networkA", "manufacturer": {"name": "NetworkInc"}},
    "platform": {"name": "Cisco IOS"}, "location": {"id": UUID_BER, "name": "Berlin"},
    "primary_ip4": {"address": "10.0.0.2/24"}, "tags": [{"name": "lab"}],
}
DEVICE_DETAIL = {
    **DEVICE_ROW, "asset_tag": None, "comments": "", "rack": None, "tenant": None,
    "primary_ip6": None,
}
INTERFACE_ROWS = [
    {"name": "eth0", "type": "VIRTUAL", "enabled": True, "mac_address": None,
     "description": "", "status": {"name": "Active"},
     "ip_addresses": [{"address": "10.0.0.2/24"}]},
]
IP_ROW = {
    "id": "cccccccc-cccc-cccc-cccc-cccccccccccc", "address": "10.0.0.2/24", "dns_name": "d1.lab",
    "type": "HOST", "description": "", "status": {"name": "Active"}, "role": None,
    "parent": {"prefix": "10.0.0.0/24", "namespace": {"name": "black"}}, "tenant": None,
    "tags": [], "interfaces": [{"name": "eth0", "device": {"name": "device-1"}}],
    "primary_ip4_for": [{"name": "device-1"}],
}
PREFIX_ROW = {
    "id": "dddddddd-dddd-dddd-dddd-dddddddddddd", "prefix": "10.0.0.0/24", "type": "NETWORK",
    "status": {"name": "Active"}, "role": None, "namespace": {"name": "black"},
    "description": "Auto-created", "tenant": None, "vlan": {"vid": 10, "name": "mgmt"},
    "locations": [{"name": "Berlin"}], "tags": [], "parent": {"prefix": "10.0.0.0/16"},
}
VOCAB_ROWS = {
    "namespaces": [{"name": "Global"}, {"name": "black"}],
    "device_types": [
        {"model": "networkA", "manufacturer": {"name": "NetworkInc"}},
        {"model": "serverA", "manufacturer": {"name": "ServerInc"}},
    ],
    "platforms": [
        {"name": "Cisco IOS", "manufacturer": None, "network_driver": "cisco_ios"},
        {"name": "ServerPlatform", "manufacturer": {"name": "ServerInc"}, "network_driver": ""},
    ],
    "roles": [{"name": "Network"}, {"name": "Server"}],
    "statuses": [{"name": "Active"}, {"name": "Planned"}],
    "tags": [{"name": "lab"}],
    "location_types": [
        {"name": "Country", "nestable": False, "parent": None, "content_types": []},
        {"name": "City", "nestable": False, "parent": {"name": "Country"}, "content_types": []},
        {"name": "Site", "nestable": False, "parent": {"name": "City"}, "content_types": []},
        {"name": "State", "nestable": False, "parent": None, "content_types": []},
    ],
}


class FakeNautobot:
    """Canned Nautobot: records every call so tests can assert on filters sent."""

    def __init__(self) -> None:
        self.page_calls: list[dict[str, Any]] = []
        self.graphql_calls: list[tuple[str, dict[str, Any] | None]] = []
        self.list_rows: dict[str, list[dict[str, Any]]] = {
            "locations": LOCATION_ROWS, "interfaces": INTERFACE_ROWS,
        }
        self.has_more = False
        self.device_detail: dict[str, Any] | None = dict(DEVICE_DETAIL)
        self.fail_with: NautobotError | None = None

    async def list_all(self, root, selection, filters=None, **_):
        if self.fail_with:
            raise self.fail_with
        if root == "locations":
            return LOCATION_ROWS
        return VOCAB_ROWS[root]

    async def list_page(self, root, selection, filters, *, limit, offset):
        if self.fail_with:
            raise self.fail_with
        self.page_calls.append(
            {"root": root, "filters": dict(filters), "limit": limit, "offset": offset}
        )
        return Page(items=tuple(self.list_rows.get(root, [])), has_more=self.has_more)

    async def graphql(self, query, variables=None):
        self.graphql_calls.append((query, variables))
        return {"location": LOCATION_ROWS[1], "device": self.device_detail}


@pytest.fixture
def nautobot():
    return FakeNautobot()


class McpHarness:
    """Talks to the server over the real MCP protocol, in memory, one connection per call.

    (A fixture that keeps one ``Client`` open would enter and leave anyio's task group in
    different pytest-asyncio tasks, which anyio rejects.)
    """

    def __init__(self, server) -> None:
        self._server = server

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None):
        async with Client(self._server) as client:
            return await client.call_tool(name, arguments or {})

    async def list_tools(self):
        async with Client(self._server) as client:
            return await client.list_tools()

    async def instructions(self) -> str | None:
        async with Client(self._server) as client:
            return client.instructions


@pytest.fixture
def mcp_client(nautobot):
    app = AppContext(client=nautobot, vocabularies=VocabularyCache(nautobot))
    return McpHarness(build_server(app, instructions="test instructions"))
