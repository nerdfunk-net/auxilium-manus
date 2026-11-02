"""Canned Nautobot data and a fake client for the query tests."""

from typing import Any

import pytest

from nautobot_read.client import NautobotError, Page, TooManyRowsError
from nautobot_read.context import QueryContext
from nautobot_read.errors import EXPECTED_ERRORS
from nautobot_read.queries import dcim, free_ip, ipam, organization, virtual_chassis
from nautobot_read.vocabularies import VocabularyCache

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
UUID_PFX = "dddddddd-dddd-dddd-dddd-dddddddddddd"
UUID_PFX_BLACK = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
UUID_PFX_WIDE = "ffffffff-ffff-ffff-ffff-ffffffffffff"
UUID_VC = "99999999-9999-9999-9999-999999999999"
VC_ROW = {
    "id": UUID_VC, "name": "LAB.local.zz",
    "members": [
        {"id": UUID_DEV2, "name": "LAB:2.local.zz", "serial": "SN2", "vc_position": 2,
         "vc_priority": 1, "device_type": {"model": "C9300-24P"}, "platform": None,
         "primary_ip4": None, "vc_master_for": None},
        {"id": UUID_DEV1, "name": "LAB.local.zz", "serial": "SN1", "vc_position": 1,
         "vc_priority": 15, "device_type": {"model": "C9300-48P"},
         "platform": {"name": "Cisco IOS-XE", "network_driver": "cisco_xe"},
         "primary_ip4": {"address": "10.0.0.1/24"},
         "vc_master_for": {"id": UUID_VC, "name": "LAB.local.zz"}},
    ],
}
VOCAB_ROWS = {
    "virtual_chassis": [{"name": "LAB.local.zz"}, {"name": "OTHER"}],
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
        self.rest_calls: list[str] = []
        self.too_many_locations = False
        self.graphql_override: dict[str, Any] | None = None
        self.vc_names: list[dict[str, Any]] | None = None
        self.location_lookup: list[dict[str, Any]] = []
        self.available: Any = [{"address": f"10.0.0.{n}/24"} for n in range(0, 12)]

    async def list_all(self, root, selection, filters=None, **_):
        if self.fail_with:
            raise self.fail_with
        if root == "locations" and self.too_many_locations:
            raise TooManyRowsError("Nautobot has more than 5000 locations; too many to load.")
        if root == "locations":
            return LOCATION_ROWS
        if root == "virtual_chassis" and self.vc_names is not None:
            return self.vc_names
        return VOCAB_ROWS[root]

    async def list_page(self, root, selection, filters, *, limit, offset):
        if self.fail_with:
            raise self.fail_with
        self.page_calls.append(
            {"root": root, "filters": dict(filters), "limit": limit, "offset": offset}
        )
        return Page(items=tuple(self.list_rows.get(root, [])), has_more=self.has_more)

    async def rest_get(self, endpoint):
        self.rest_calls.append(endpoint)
        if self.fail_with:
            raise self.fail_with
        return self.available

    async def graphql(self, query, variables=None):
        self.graphql_calls.append((query, variables))
        if self.graphql_override is not None:
            return self.graphql_override
        return {"location": LOCATION_ROWS[1], "device": self.device_detail}


@pytest.fixture
def nautobot():
    return FakeNautobot()


@pytest.fixture
def ctx(nautobot):
    return QueryContext(client=nautobot, vocabularies=VocabularyCache(nautobot))


def _query(name: str):
    for module in (organization, dcim, ipam, free_ip, virtual_chassis):
        if hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(name)


async def run(ctx, name: str, **kwargs):
    """Call the query function ``name`` the way a tool wrapper does."""
    return await _query(name)(ctx, **kwargs)


async def error_text(ctx, name: str, **kwargs) -> str:
    """The message of the expected error ``name`` raises (the text the model reads)."""
    with pytest.raises(EXPECTED_ERRORS) as exc:
        await run(ctx, name, **kwargs)
    return str(exc.value)
