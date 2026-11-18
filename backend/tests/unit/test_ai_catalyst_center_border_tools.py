"""list_catalyst_center_border_handoffs: rows, filters, gates, partial data, errors."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from models.catalyst_center import CatalystCenterDevice
from models.catalyst_center_facts import (
    CatalystCenterBorderHandoffs,
    CatalystCenterFabricDevice,
    CatalystCenterIpTransitHandoff,
    CatalystCenterLayer2Handoff,
    CatalystCenterSdaTransitHandoff,
    CatalystCenterTransit,
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
from services.ai_assistant.tools.catalyst_center_border_tools import (
    build_catalyst_center_border_tools,
)
from services.ai_assistant.tools.catalyst_center_tools import CATALYST_READER_KEY
from services.ai_assistant.tools.playbook_tools import known_general_tool_names
from services.catalyst_center.common.exceptions import (
    CatalystCenterAPIError,
    CatalystCenterNotFoundError,
)

ALL = SharingPolicy(inventory=True, addresses=True, content=True)
INVENTORY_ONLY = SharingPolicy(inventory=True)
BERLIN, MUNICH = "Global/Berlin", "Global/Munich"


def _border(device_id: str, site: str) -> CatalystCenterFabricDevice:
    return CatalystCenterFabricDevice(
        device_id=device_id, fabric_id="f-" + device_id, fabric_site=site, roles=("BORDER_NODE",)
    )


BORDERS = (_border("d-b", BERLIN), _border("d-a", MUNICH), _border("d-c", BERLIN))
NAMES = {"d-a": "border-a", "d-b": "border-b", "d-c": "border-c", "d-cp1": "cp-1", "d-cp2": "cp-2"}
TRANSITS = (
    CatalystCenterTransit(
        id="t2",
        name="WAN",
        transit_type="IP_BASED_TRANSIT",
        routing_protocol="BGP",
        autonomous_system_number="65001",
    ),
    CatalystCenterTransit(
        id="t1",
        name="Campus-SDA",
        transit_type="SDA_LISP_PUB_SUB_TRANSIT",
        multicast_over_transit=False,
        control_plane_device_ids=("d-cp1", "d-cp2", "d-unknown"),
    ),
)


def _handoffs(device_id: str, n_ip: int = 1, unavailable=()) -> CatalystCenterBorderHandoffs:
    return CatalystCenterBorderHandoffs(
        device_id=device_id,
        ip_transits=tuple(
            CatalystCenterIpTransitHandoff(
                transit_id="t1",
                transit_name="WAN",
                interface_name=f"Te1/0/{i}",
                virtual_network="CORP",
                vlan_id=3000 + i,
                local_ip="10.9.9.1/30",
                remote_ip="10.9.9.2/30",
                remote_ipv6="2001:db8::2",
            )
            for i in range(n_ip)
        ),
        sda_transits=(
            CatalystCenterSdaTransitHandoff(transit_name="SDA", connected_to_internet=True),
        ),
        layer2=(CatalystCenterLayer2Handoff(interface_name="Gi1/0/5", internal_vlan_id=1021),),
        unavailable=tuple(unavailable),
    )


class FakeBorder:
    def __init__(
        self, borders=BORDERS, error: Exception | None = None, n_ip: int = 1, transits=None
    ) -> None:
        self.borders, self.error, self.n_ip = borders, error, n_ip
        self.transits = TRANSITS if transits is None else transits
        self.asked: list[str] = []
        self.site_asked: list[str | None] = []

    async def list_borders(self, *, fabric_site=None):
        self.site_asked.append(fabric_site)
        if self.error:
            raise self.error
        return tuple(b for b in self.borders if fabric_site in (None, b.fabric_site)), ()

    async def list_transits(self, *, missing_ok=True):
        if self.error:
            raise self.error
        return {t.id: t for t in self.transits}

    async def read_handoffs(self, border, transits):
        self.asked.append(border.device_id)
        return _handoffs(
            border.device_id, self.n_ip, ("layer2",) if border.device_id == "d-c" else ()
        )


class FakeDevices:
    async def get_devices_by_ids(self, ids):
        return tuple(
            CatalystCenterDevice(id=i, hostname=NAMES[i], management_ip="10.0.0.9", raw={})
            for i in ids
            if i in NAMES
        )


class FakeReader:
    def __init__(self, border: FakeBorder | None = None, error: Exception | None = None) -> None:
        self.border, self.error, self.calls = border or FakeBorder(), error, 0

    async def sources(self):
        self.calls += 1
        if self.error:
            raise self.error
        return (CatalystSource("lab-dnac", FakeDevices(), None, border=self.border),)  # type: ignore[arg-type]


def _call(
    reader: Any,
    sharing: SharingPolicy = ALL,
    /,
    tool: str = "list_catalyst_center_border_handoffs",
    **tool_input: Any,
) -> ToolOutput:
    ctx = ToolContext(
        user_id=1, redactor=Redactor(), extras={CATALYST_READER_KEY: reader}, sharing=sharing
    )
    box = Toolbox(build_catalyst_center_border_tools(), ctx)
    call = ToolCall(id="1", name=tool, input=tool_input)
    return asyncio.run(box.execute(call))


def _json(out: ToolOutput) -> dict[str, Any]:
    assert not out.is_error, out.content
    return json.loads(out.content)


def test_borders_are_sorted_by_name_with_all_three_handoff_kinds() -> None:
    reader = FakeReader()
    source = _json(_call(reader))["sources"][0]
    first = source["borders"][0]

    assert [b["hostname"] for b in source["borders"]] == ["border-a", "border-b", "border-c"]
    assert source["total"] == 3 and source["has_more"] is False
    ip = first["layer3_ip_transit_handoffs"]
    assert ip["count"] == 1 and ip["items"][0] == {
        "transit_name": "WAN",
        "interface_name": "Te1/0/0",
        "virtual_network": "CORP",
        "vlan_id": 3000,
        "local_ip": "10.9.9.1/30",
        "remote_ip": "10.9.9.2/30",
        "remote_ipv6": "2001:db8::2",
    }
    assert first["layer3_sda_transit_handoffs"]["items"][0]["connected_to_internet"] is True
    assert first["layer2_handoffs"]["items"][0]["internal_vlan_id"] == 1021
    assert first["management_ip"] == "10.0.0.9"
    assert "unavailable" not in first and source["borders"][2]["unavailable"] == ["layer2"]


def test_filters_and_paging_read_only_the_page() -> None:
    reader = FakeReader()
    named = _json(_call(reader, name_contains="BORDER-B"))["sources"][0]
    site = _json(_call(reader, fabric_site=MUNICH))["sources"][0]
    reader.border.asked.clear()
    page = _json(_call(reader, limit=1, offset=1))["sources"][0]

    assert [b["hostname"] for b in named["borders"]] == ["border-b"]
    assert [b["hostname"] for b in site["borders"]] == ["border-a"]
    assert reader.border.site_asked[1] == MUNICH
    assert page["has_more"] is True and [b["hostname"] for b in page["borders"]] == ["border-b"]
    assert reader.border.asked == ["d-b"]  # handoffs of the page only


def test_rows_per_kind_are_capped_with_a_count() -> None:
    reader = FakeReader(FakeBorder(n_ip=25))
    ip = _json(_call(reader, limit=1))["sources"][0]["borders"][0]["layer3_ip_transit_handoffs"]

    assert ip["count"] == 25 and len(ip["items"]) == 10


def test_addresses_need_the_addresses_switch() -> None:
    out = _json(_call(FakeReader(), INVENTORY_ONLY))
    border = out["sources"][0]["borders"][0]
    item = border["layer3_ip_transit_handoffs"]["items"][0]

    assert "management_ip" not in border
    assert not {"local_ip", "remote_ip", "remote_ipv6"} & set(item) and item["interface_name"]
    assert "remote_ip" in out["withheld_fields"]


def test_inventory_switch_off_sends_nothing_and_no_border_is_an_answer() -> None:
    reader = FakeReader()
    assert _json(_call(reader, SharingPolicy()))["not_shared"] == "inventory_data"
    assert reader.calls == 0
    empty = _json(_call(FakeReader(FakeBorder(borders=()))))
    assert "No SD-Access border node" in empty["message"]


def test_errors_are_fixed_sentences_and_input_is_checked() -> None:
    missing = _call(FakeReader(FakeBorder(error=CatalystCenterNotFoundError("x"))))
    failed = _call(FakeReader(FakeBorder(error=CatalystCenterAPIError("secret https://dnac/x"))))

    assert missing.is_error and "no SD-Access API" in missing.content
    assert failed.is_error and "secret" not in failed.content
    assert (
        "No Cisco Catalyst Center source"
        in _call(FakeReader(error=CatalystNotConfiguredError())).content
    )
    assert "cannot read Catalyst Center" in _call(FakeReader(error=CatalystAccessError())).content
    assert _call(FakeReader(), limit=6).is_error and _call(FakeReader(), site="x").is_error
    assert "list_catalyst_center_border_handoffs" in known_general_tool_names()


def _transits(reader: Any, sharing: SharingPolicy = ALL, **tool_input: Any) -> ToolOutput:
    return _call(reader, sharing, tool="list_catalyst_center_transits", **tool_input)


def test_transits_show_type_settings_and_control_plane_names() -> None:
    source = _json(_transits(FakeReader()))["sources"][0]
    rows = {t["name"]: t for t in source["transits"]}

    assert list(rows) == ["Campus-SDA", "WAN"] and source["total"] == 2
    assert rows["WAN"] == {
        "name": "WAN",
        "transit_type": "IP_BASED_TRANSIT",
        "routing_protocol": "BGP",
        "autonomous_system_number": "65001",
    }
    sda = rows["Campus-SDA"]
    assert sda["multicast_over_transit"] is False and sda["control_plane_count"] == 3
    # Known devices by hostname, an id the inventory does not know stays as it is.
    assert sda["control_plane_devices"] == ["cp-1", "cp-2", "d-unknown"]
    assert "id" not in sda and "control_plane_device_ids" not in sda


def test_transits_filter_and_page() -> None:
    reader = FakeReader()
    by_type = _json(_transits(reader, transit_type="IP_BASED_TRANSIT"))["sources"][0]
    named = _json(_transits(reader, name_contains="CAMPUS"))["sources"][0]
    page = _json(_transits(reader, limit=1, offset=1))["sources"][0]

    assert [t["name"] for t in by_type["transits"]] == ["WAN"]
    assert [t["name"] for t in named["transits"]] == ["Campus-SDA"]
    assert [t["name"] for t in page["transits"]] == ["WAN"] and page["has_more"] is False
    assert _transits(reader, transit_type="OTHER").is_error


def test_transits_need_the_inventory_switch_and_report_none_as_an_answer() -> None:
    reader = FakeReader()
    assert _json(_transits(reader, SharingPolicy()))["not_shared"] == "inventory_data"
    assert reader.calls == 0
    empty = _json(_transits(FakeReader(FakeBorder(transits=()))))
    assert "No transit network" in empty["message"]


def test_transit_errors_are_fixed_sentences() -> None:
    missing = _transits(FakeReader(FakeBorder(error=CatalystCenterNotFoundError("x"))))
    failed = _transits(
        FakeReader(FakeBorder(error=CatalystCenterAPIError("secret https://dnac/x")))
    )

    assert missing.is_error and "no SD-Access API" in missing.content
    assert failed.is_error and "secret" not in failed.content
    assert "list_catalyst_center_transits" in known_general_tool_names()


def test_one_failing_border_does_not_discard_the_others() -> None:
    from services.catalyst_center.common.exceptions import CatalystCenterRateLimitError

    border = FakeBorder()
    original = border.read_handoffs

    async def flaky(b, transits):
        if b.device_id == BORDERS[0].device_id:
            raise CatalystCenterRateLimitError("secret https://dnac/x")
        return await original(b, transits)

    border.read_handoffs = flaky  # type: ignore[method-assign]
    out = _call(FakeReader(border), limit=5)
    rows = _json(out)["sources"][0]["borders"]

    assert len(rows) == len(BORDERS)
    failed = [r for r in rows if "error" in r]
    assert len(failed) == 1 and "secret" not in out.content
    assert any("layer2_handoffs" in r for r in rows)


def test_rows_past_the_cap_are_flagged_truncated() -> None:
    source = _json(_call(FakeReader(FakeBorder(n_ip=12))))["sources"][0]
    ip = source["borders"][0]["layer3_ip_transit_handoffs"]

    assert ip["count"] == 12 and len(ip["items"]) == 10 and ip["truncated"] is True
