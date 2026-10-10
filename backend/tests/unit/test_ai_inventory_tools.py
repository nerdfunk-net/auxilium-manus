"""Inventory tools: class B opt-in, aggregation over all devices, access errors."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from models.ai_assistant import InventoryContext
from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.providers.base import ToolCall
from services.ai_assistant.surfaces import build_inventory_session
from services.ai_assistant.tools.inventory_tools import (
    InventoryAccessError,
    InventoryNotFoundError,
)

DEVICES = [
    {
        "id": f"id-{i}",
        "name": f"sw-{i:03d}",
        "role": "access" if i % 4 else "core",
        "platform": "IOS-XE",
        "location": "HQ" if i < 70 else "DC",
        "status": "Active",
        "primary_ip4": f"10.0.0.{i}",
        "custom_fields": {"snmp_password": "hunter2hunter2", "owner": "net-team"},
        "tags": [],
    }
    for i in range(100)
]


class FakeInventoryReader:
    def __init__(self, denied: bool = False) -> None:
        self.denied = denied

    async def list_inventories(self):
        if self.denied:
            raise InventoryAccessError
        return [{"id": 1, "name": "LAB", "type": "filter", "scope": "global"}]

    async def resolve_inventory(self, inventory_id):
        if self.denied:
            raise InventoryAccessError
        if inventory_id != 1:
            raise InventoryNotFoundError
        return {"id": 1, "name": "LAB", "inventory_type": "filter", "devices": DEVICES}

    async def search_devices(self, search, limit):
        return [d for d in DEVICES if search in d["name"]][:limit]

    async def get_device_attributes(self, device_id, attributes):
        if device_id != "id-1":
            raise InventoryNotFoundError
        return {
            "name": "sw-001",
            "role": "access",
            "primary_ip4": {"address": "10.0.0.1/24"},
            "custom_fields": DEVICES[1]["custom_fields"],
            "config_context": {"tacacs": {"shared_secret": "ctxsecret123"}, "ntp": "10.9.9.9"},
            "comments": "free text",
        }


def _session(
    *, inventory=False, denied=False, addresses=False, custom_fields=False, config_context=False
):
    return build_inventory_session(
        user_id=1,
        context=InventoryContext(surface="inventory", source_id="nb"),
        reader=FakeInventoryReader(denied),
        sharing=SharingPolicy(
            inventory=inventory,
            addresses=addresses,
            custom_fields=custom_fields,
            config_context=config_context,
        ),
    )


def _call(session, name: str, **input_: Any):
    return asyncio.run(session.toolbox.execute(ToolCall("1", name, input_)))


def test_surface_offers_four_read_tools() -> None:
    names = {s.name for s in _session().toolbox.specs()}

    assert names == {
        "list_inventories",
        "resolve_inventory",
        "search_devices",
        "get_device_attributes",
    }


def test_prompt_states_the_sharing_choice() -> None:
    assert "nothing about individual devices" in _session().system
    assert "device data" in _session(inventory=True).system


def test_unshared_resolve_gives_only_the_size() -> None:
    out = _call(_session(), "resolve_inventory", inventory_id=1)

    data = json.loads(out.content)
    assert data["total_count"] == 100
    assert data["devices"]["not_shared"] == "inventory_data"
    assert "sw-001" not in out.content and "counts_by" not in out.content


def test_shared_resolve_counts_cover_all_devices_but_rows_are_limited() -> None:
    out = _call(_session(inventory=True), "resolve_inventory", inventory_id=1, limit=5)

    data = json.loads(out.content)
    assert data["total_count"] == 100 and len(data["devices"]) == 5
    assert data["counts_by"]["role"] == {"access": 75, "core": 25}
    assert data["counts_by"]["location"] == {"HQ": 70, "DC": 30}
    assert "5 of 100" in data["note"]


def test_requested_fields_are_projected_and_unknown_ones_ignored() -> None:
    out = _call(
        _session(inventory=True, addresses=True),
        "resolve_inventory",
        inventory_id=1,
        limit=1,
        fields=["name", "primary_ip4", "bogus"],
    )

    device = json.loads(out.content)["devices"][0]
    assert set(device) == {"id", "name", "primary_ip4"}


def test_secret_named_custom_fields_are_redacted() -> None:
    out = _call(
        _session(inventory=True, custom_fields=True),
        "resolve_inventory",
        inventory_id=1,
        limit=1,
        fields=["custom_fields"],
    )

    assert "hunter2" not in out.content and "net-team" in out.content


def test_search_and_attributes_are_not_shared_by_default() -> None:
    s = _session()

    assert "not_shared" in _call(s, "search_devices", search="sw").content
    assert "not_shared" in _call(s, "get_device_attributes", device_id="id-1").content
    assert "sw-001" not in _call(s, "search_devices", search="sw").content


def test_shared_search_and_attributes_redact_secrets() -> None:
    s = _session(inventory=True, addresses=True, custom_fields=True, config_context=True)

    found = _call(s, "search_devices", search="sw-00", limit=3)
    attrs = _call(s, "get_device_attributes", device_id="id-1")

    assert found.content.count('"name"') == 3 and "10.0.0." in found.content
    assert "hunter2" not in attrs.content and "net-team" in attrs.content
    assert "ctxsecret123" not in attrs.content  # secret-named key inside the config context


# -- fine-grained categories --------------------------------------------------------------------


def _resolved(session, fields):
    out = _call(session, "resolve_inventory", inventory_id=1, limit=1, fields=fields)
    return json.loads(out.content)


def test_each_category_needs_its_own_switch() -> None:
    fields = ["name", "primary_ip4", "serial", "custom_fields"]

    base = _resolved(_session(inventory=True), fields)
    addr = _resolved(_session(inventory=True, addresses=True), fields)
    custom = _resolved(_session(inventory=True, custom_fields=True), fields)

    assert set(base["devices"][0]) == {"id", "name"}
    assert base["withheld_fields"] == {
        "primary_ip4": "device_addresses",
        "serial": "device_addresses",
        "custom_fields": "custom_fields",
    }
    assert set(addr["devices"][0]) == {"id", "name", "primary_ip4", "serial"}
    assert set(custom["devices"][0]) == {"id", "name", "custom_fields"}


def test_a_category_without_the_base_switch_shares_nothing() -> None:
    data = _resolved(
        _session(inventory=False, addresses=True, custom_fields=True, config_context=True),
        ["name", "primary_ip4"],
    )

    assert data["devices"]["not_shared"] == "inventory_data"
    assert "10.0.0." not in json.dumps(data)


def test_attributes_are_allow_listed_by_category() -> None:
    base = json.loads(
        _call(_session(inventory=True), "get_device_attributes", device_id="id-1").content
    )

    assert set(base["attributes"]) == {"name", "role"}
    assert base["withheld_attributes"] == {
        "primary_ip4": "Addresses and serial numbers",
        "custom_fields": "Custom fields",
        "config_context": "Config context",
        "comments": "never",
    }
    assert "10.9.9.9" not in json.dumps(base) and "net-team" not in json.dumps(base)


def test_config_context_only_with_its_own_switch() -> None:
    out = _call(
        _session(inventory=True, config_context=True), "get_device_attributes", device_id="id-1"
    )

    data = json.loads(out.content)
    assert "config_context" in data["attributes"] and "10.9.9.9" in out.content
    assert "config_context" not in data["withheld_attributes"]
    assert "primary_ip4" in data["withheld_attributes"]


def test_unknown_attributes_are_never_shared_even_with_every_switch_on() -> None:
    out = _call(
        _session(inventory=True, addresses=True, custom_fields=True, config_context=True),
        "get_device_attributes",
        device_id="id-1",
    )

    data = json.loads(out.content)
    assert data["withheld_attributes"] == {"comments": "never"}
    assert "free text" not in out.content


def test_unknown_inventory_and_denied_access() -> None:
    assert _call(_session(), "resolve_inventory", inventory_id=9).is_error
    denied = _call(_session(denied=True), "list_inventories")

    assert denied.is_error and "cannot read Nautobot" in denied.content


def test_unknown_device_is_an_error() -> None:
    out = _call(_session(inventory=True), "get_device_attributes", device_id="nope")

    assert out.is_error
