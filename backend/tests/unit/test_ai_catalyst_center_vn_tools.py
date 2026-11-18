"""list_catalyst_center_virtual_networks: rows, VLANs, filters, gates, errors."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from models.catalyst_center_facts import (
    CatalystCenterLayer2Network,
    CatalystCenterVirtualNetwork,
    CatalystCenterVirtualNetworks,
)
from services.ai_assistant.catalyst_center_reader import (
    CatalystAccessError,
    CatalystNotConfiguredError,
    CatalystSource,
)
from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.providers.base import ToolCall
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.tools.base import Toolbox, ToolContext, ToolOutput
from services.ai_assistant.tools.catalyst_center_tools import CATALYST_READER_KEY
from services.ai_assistant.tools.catalyst_center_vn_tools import build_catalyst_center_vn_tools
from services.ai_assistant.tools.playbook_tools import known_general_tool_names
from services.catalyst_center.common.exceptions import (
    CatalystCenterAPIError,
    CatalystCenterNotFoundError,
)

ALL = SharingPolicy(inventory=True, addresses=True, content=True)
BERLIN, MUNICH = "Global/Berlin", "Global/Munich"


def _vlan(name: str, vid: int, vn: str | None, site: str | None = BERLIN):
    return CatalystCenterLayer2Network(
        vlan_name=name,
        vlan_id=vid,
        traffic_type="DATA",
        layer3_virtual_network=vn,
        fabric_site=site,
    )


DATA = CatalystCenterVirtualNetworks(
    networks=(
        CatalystCenterVirtualNetwork(name="INFRA_VN", id="v2"),
        CatalystCenterVirtualNetwork(name="CORP", id="v1", fabric_sites=(BERLIN, MUNICH)),
        CatalystCenterVirtualNetwork(name="GUEST", id="v3", fabric_sites=(MUNICH,)),
    ),
    layer2=(
        _vlan("users", 1021, "CORP"),
        _vlan("phones", 1022, "corp"),
        _vlan("guests", 1030, "GUEST", MUNICH),
        _vlan("stray", 1099, "GONE"),
    ),
)


class FakeFabric:
    def __init__(self, data=DATA, error: Exception | None = None) -> None:
        self.data, self.error = data, error

    async def list_virtual_networks(self):
        if self.error:
            raise self.error
        return self.data


class FakeReader:
    def __init__(self, fabric: FakeFabric | None = None, error: Exception | None = None) -> None:
        self.fabric, self.error, self.calls = fabric or FakeFabric(), error, 0

    async def sources(self):
        self.calls += 1
        if self.error:
            raise self.error
        return (CatalystSource("lab-dnac", None, None, self.fabric),)  # type: ignore[arg-type]


def _call(reader: Any, sharing: SharingPolicy = ALL, **tool_input: Any) -> ToolOutput:
    ctx = ToolContext(
        user_id=1, redactor=Redactor(), extras={CATALYST_READER_KEY: reader}, sharing=sharing
    )
    box = Toolbox(build_catalyst_center_vn_tools(), ctx)
    call = ToolCall(id="1", name="list_catalyst_center_virtual_networks", input=tool_input)
    return asyncio.run(box.execute(call))


def _json(out: ToolOutput) -> dict[str, Any]:
    assert not out.is_error, out.content
    return json.loads(out.content)


def test_networks_are_sorted_with_sites_deployment_and_vlans() -> None:
    source = _json(_call(FakeReader()))["sources"][0]
    rows = {r["name"]: r for r in source["virtual_networks"]}

    assert list(rows) == ["CORP", "GUEST", "INFRA_VN"] and source["total"] == 3
    assert rows["CORP"]["fabric_sites"] == [BERLIN, MUNICH] and rows["CORP"]["deployed"] is True
    assert rows["INFRA_VN"]["deployed"] is False and rows["INFRA_VN"]["fabric_sites"] == []
    # VLANs attach by network name, in any case.
    assert [v["vlan_name"] for v in rows["CORP"]["layer2_networks"]] == ["users", "phones"]
    assert rows["CORP"]["layer2_count"] == 2
    assert rows["CORP"]["layer2_networks"][0] == {
        "vlan_name": "users",
        "vlan_id": 1021,
        "traffic_type": "DATA",
        "fabric_site": BERLIN,
    }
    assert source["layer2_without_virtual_network_count"] == 1
    assert source["layer2_without_virtual_network"][0]["vlan_name"] == "stray"


def test_filters_page_and_layer2_switch() -> None:
    reader = FakeReader()
    named = _json(_call(reader, name_contains="GU"))["sources"][0]
    munich = _json(_call(reader, fabric_site=MUNICH))["sources"][0]
    page = _json(_call(reader, limit=1, offset=1))["sources"][0]
    bare = _json(_call(reader, include_layer2=False))["sources"][0]

    assert [r["name"] for r in named["virtual_networks"]] == ["GUEST"]
    assert "layer2_without_virtual_network" not in named  # a name filter is about networks only
    assert [r["name"] for r in munich["virtual_networks"]] == ["CORP", "GUEST"]
    assert [v["vlan_name"] for v in munich["virtual_networks"][0]["layer2_networks"]] == []
    assert [r["name"] for r in page["virtual_networks"]] == ["GUEST"] and page["has_more"] is True
    assert "layer2_networks" not in bare["virtual_networks"][0]
    assert "layer2_without_virtual_network" not in bare


def test_missing_layer2_api_is_noted() -> None:
    data = CatalystCenterVirtualNetworks(networks=DATA.networks, layer2_available=False)
    source = _json(_call(FakeReader(FakeFabric(data))))["sources"][0]

    assert "layer 2" in source["layer2_note"]
    assert "layer2_networks" not in source["virtual_networks"][0]


def test_inventory_switch_off_sends_nothing() -> None:
    reader = FakeReader()
    out = _json(_call(reader, SharingPolicy()))

    assert out["not_shared"] == "inventory_data" and reader.calls == 0


def test_errors_are_fixed_sentences_and_no_source_passes_through() -> None:
    missing = _call(FakeReader(FakeFabric(error=CatalystCenterNotFoundError("x"))))
    failed = _call(FakeReader(FakeFabric(error=CatalystCenterAPIError("secret https://dnac/x"))))

    assert missing.is_error and "no SD-Access API" in missing.content
    assert failed.is_error and "secret" not in failed.content
    assert (
        "No Cisco Catalyst Center source"
        in _call(FakeReader(error=CatalystNotConfiguredError())).content
    )
    assert "cannot read Catalyst Center" in _call(FakeReader(error=CatalystAccessError())).content


def test_unknown_input_is_refused_and_tool_is_registered() -> None:
    assert _call(FakeReader(), site="x").is_error
    assert _call(FakeReader(), limit=51).is_error
    assert "list_catalyst_center_virtual_networks" in known_general_tool_names()


def test_a_fabric_site_filter_also_limits_the_vlans_without_a_network() -> None:
    munich = _json(_call(FakeReader(), fabric_site=MUNICH))["sources"][0]

    assert "layer2_without_virtual_network" not in munich  # "stray" is not in Munich
