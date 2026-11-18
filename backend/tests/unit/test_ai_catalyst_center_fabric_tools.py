"""list_catalyst_center_fabric: overlay/underlay rows, filters, gates, errors, wiring."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from models.catalyst_center import CatalystCenterDevice, CatalystCenterSite
from models.catalyst_center_facts import (
    CatalystCenterFabric,
    CatalystCenterFabricDevice,
    CatalystCenterFabricSite,
    CatalystCenterUnderlayDevice,
    CatalystCenterVirtualNetwork,
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
from services.ai_assistant.tools.catalyst_center_fabric_tools import (
    build_catalyst_center_fabric_tools,
)
from services.ai_assistant.tools.catalyst_center_tools import CATALYST_READER_KEY
from services.ai_assistant.tools.playbook_tools import known_general_tool_names
from services.catalyst_center.common.exceptions import (
    CatalystCenterAPIError,
    CatalystCenterNotFoundError,
    CatalystCenterTooManyDevicesError,
    CatalystCenterTooManySitesError,
    CatalystCenterUnknownSiteError,
    CatalystCenterValidationError,
)

ALL = SharingPolicy(inventory=True, addresses=True, content=True)
INVENTORY_ONLY = SharingPolicy(inventory=True)
NOTHING = SharingPolicy()
BERLIN, MUNICH = "Global/Berlin", "Global/Munich"

FABRIC = CatalystCenterFabric(
    sites=(
        CatalystCenterFabricSite(fabric_id="f1", site_id="s1", site_name=BERLIN),
        CatalystCenterFabricSite(fabric_id="f2", site_id="s2", site_name=MUNICH),
    ),
    devices=(
        CatalystCenterFabricDevice(
            device_id="d-border", fabric_id="f1", fabric_site=BERLIN, roles=("BORDER_NODE",)
        ),
        CatalystCenterFabricDevice(
            device_id="d-edge", fabric_id="f2", fabric_site=MUNICH, roles=("EDGE_NODE",)
        ),
    ),
    virtual_networks=(CatalystCenterVirtualNetwork(name="CORP", fabric_sites=(BERLIN, MUNICH)),),
    underlay_only=(CatalystCenterUnderlayDevice(device_id="d-core", fabric_site=BERLIN),),
)


def _device(device_id: str, host: str, ip: str, role: str = "ACCESS") -> CatalystCenterDevice:
    return CatalystCenterDevice(
        id=device_id,
        role=role,
        hostname=host,
        management_ip=ip,
        serial_number="SN-" + host,
        platform_id="C9500",
        reachability_status="Reachable",
        raw={},
    )


class FakeFabric:
    def __init__(self, fabric: CatalystCenterFabric = FABRIC, error: Exception | None = None):
        self.fabric, self.error, self.calls, self.sites_asked = fabric, error, [], []

    async def read_fabric(self, *, include_underlay: bool = False, fabric_site: str | None = None):
        self.calls.append(include_underlay)
        self.sites_asked.append(fabric_site)
        if self.error:
            raise self.error
        return self.fabric


class FakeDevices:
    def __init__(self) -> None:
        self.asked: list[list[str]] = []
        self.site_error: Exception | None = None
        self.search_error: Exception | None = None
        self.filters: list = []
        self._by_site = {"Global/Berlin": ["d-edge", "d-border"]}
        self._all = {
            "d-border": _device("d-border", "border-1", "10.0.0.1", "BORDER ROUTER"),
            "d-edge": _device("d-edge", "edge-1", "10.0.0.2"),
        }

    async def search_devices(self, filters, *, max_devices=None):
        self.filters.append(filters)
        if self.search_error:
            raise self.search_error
        return tuple(
            self._all[i]
            for i in self._by_site.get(filters.sites[0], [])
            if (not filters.roles or self._all[i].role in filters.roles)
        )

    async def list_sites(self):
        if self.site_error:
            raise self.site_error
        return tuple(
            CatalystCenterSite(id=str(i), name=h.rsplit("/", 1)[-1], name_hierarchy=h)
            for i, h in enumerate(["Global/Munich", "Global", "Global/Berlin", "Global/Berlin/HQ"])
        )

    async def get_devices_by_ids(self, ids: list[str]):
        self.asked.append(ids)
        return tuple(self._all[i] for i in ids if i in self._all)


class FakeReader:
    def __init__(self, fabric: FakeFabric | None = None, error: Exception | None = None):
        self.fabric = fabric or FakeFabric()
        self.devices = FakeDevices()
        self.error, self.calls = error, 0

    async def sources(self):
        self.calls += 1
        if self.error:
            raise self.error
        return (CatalystSource("lab-dnac", self.devices, None, self.fabric),)  # type: ignore[arg-type]


def _call(
    reader: Any,
    sharing: SharingPolicy = ALL,
    /,
    tool: str = "list_catalyst_center_fabric",
    **tool_input: Any,
) -> ToolOutput:
    ctx = ToolContext(
        user_id=1, redactor=Redactor(), extras={CATALYST_READER_KEY: reader}, sharing=sharing
    )
    box = Toolbox(build_catalyst_center_fabric_tools(), ctx)
    call = ToolCall(id="1", name=tool, input=tool_input)
    return asyncio.run(box.execute(call))


def _json(out: ToolOutput) -> dict[str, Any]:
    assert not out.is_error, out.content
    return json.loads(out.content)


def test_overlay_lists_only_devices_with_a_fabric_role() -> None:
    reader = FakeReader()
    out = _json(_call(reader))
    source = out["sources"][0]

    assert [d["hostname"] for d in source["devices"]] == ["border-1", "edge-1"]
    assert all(d["in_overlay"] for d in source["devices"])
    assert source["devices"][0]["roles"] == ["BORDER_NODE"]
    assert source["virtual_networks"] == [{"name": "CORP", "fabric_sites": [BERLIN, MUNICH]}]
    assert reader.fabric.calls == [False]  # no membership reads for the overlay


def test_underlay_adds_role_less_nodes_and_marks_them() -> None:
    reader = FakeReader()
    out = _json(_call(reader, network="underlay"))
    devices = out["sources"][0]["devices"]

    assert [d["device_id"] for d in devices] == ["d-border", "d-core", "d-edge"]
    core = devices[1]
    assert core["in_overlay"] is False and core["in_underlay"] is True and core["roles"] == []
    assert core["hostname"] is None  # not in the controller inventory: no invention
    assert reader.fabric.calls == [True]


def test_filters_by_site_and_role_and_pages() -> None:
    reader = FakeReader()

    by_site = _json(_call(reader, fabric_site=MUNICH))["sources"][0]
    by_role = _json(_call(reader, role="border_node"))["sources"][0]
    paged = _json(_call(reader, limit=1, offset=1))["sources"][0]

    assert [d["device_id"] for d in by_site["devices"]] == ["d-edge"]
    assert [d["device_id"] for d in by_role["devices"]] == ["d-border"]
    assert paged["total"] == 2 and paged["has_more"] is False
    assert [d["device_id"] for d in paged["devices"]] == ["d-edge"]
    assert reader.devices.asked[-1] == ["d-edge"]  # only the page's devices are read


def test_has_more_when_the_page_is_cut() -> None:
    source = _json(_call(FakeReader(), limit=1))["sources"][0]

    assert source["has_more"] is True and source["total"] == 2


def test_addresses_need_the_addresses_switch() -> None:
    out = _json(_call(FakeReader(), INVENTORY_ONLY))
    device = out["sources"][0]["devices"][0]

    assert "management_ip" not in device and "serial_number" not in device
    assert set(out["withheld_fields"]) == {"management_ip", "serial_number"}
    assert _json(_call(FakeReader()))["sources"][0]["devices"][0]["management_ip"] == "10.0.0.1"


def test_inventory_switch_off_sends_nothing() -> None:
    reader = FakeReader()
    out = _json(_call(reader, NOTHING))

    assert out["not_shared"] == "inventory_data" and reader.calls == 0


def test_empty_fabric_is_an_answer() -> None:
    reader = FakeReader(FakeFabric(CatalystCenterFabric()))
    out = _json(_call(reader))

    assert out["sources"][0]["devices"] == []
    assert "No SD-Access fabric site" in out["message"]


def test_missing_sda_api_and_failures_are_fixed_sentences() -> None:
    missing = _call(FakeReader(FakeFabric(error=CatalystCenterNotFoundError("x"))))
    failed = _call(FakeReader(FakeFabric(error=CatalystCenterAPIError("secret https://dnac/x"))))

    assert missing.is_error and "no SD-Access API" in missing.content
    assert failed.is_error and "secret" not in failed.content and "did not answer" in failed.content


def test_no_source_and_no_access_pass_through() -> None:
    assert (
        "No Cisco Catalyst Center source"
        in _call(FakeReader(error=CatalystNotConfiguredError())).content
    )
    assert "cannot read Catalyst Center" in _call(FakeReader(error=CatalystAccessError())).content


def test_unknown_input_is_refused_and_tool_is_registered() -> None:
    assert _call(FakeReader(), site="x").is_error
    assert "list_catalyst_center_fabric" in known_general_tool_names()


def _sites(reader: Any, sharing: SharingPolicy = ALL, **tool_input: Any) -> ToolOutput:
    return _call(reader, sharing, tool="list_catalyst_center_sites", **tool_input)


def test_sites_are_listed_sorted_and_filtered() -> None:
    every = _json(_sites(FakeReader()))["sources"][0]
    berlin = _json(_sites(FakeReader(), name_contains="BERLIN"))["sources"][0]

    assert every["sites"] == ["Global", "Global/Berlin", "Global/Berlin/HQ", "Global/Munich"]
    assert every["total"] == 4 and every["source_id"] == "lab-dnac"
    assert berlin["sites"] == ["Global/Berlin", "Global/Berlin/HQ"]


def test_sites_page_and_report_has_more() -> None:
    page = _json(_sites(FakeReader(), limit=1, offset=1))["sources"][0]

    assert page["sites"] == ["Global/Berlin"] and page["has_more"] is True


def test_sites_need_the_inventory_switch() -> None:
    reader = FakeReader()
    out = _json(_sites(reader, NOTHING))

    assert out["not_shared"] == "inventory_data" and reader.calls == 0


def test_sites_failure_is_a_fixed_sentence_and_no_source_passes_through() -> None:
    reader = FakeReader()
    reader.devices.site_error = CatalystCenterAPIError("secret https://dnac/x")
    failed = _sites(reader)

    assert failed.is_error and "secret" not in failed.content
    assert (
        "No Cisco Catalyst Center source"
        in _sites(FakeReader(error=CatalystNotConfiguredError())).content
    )
    assert "list_catalyst_center_sites" in known_general_tool_names()


def _site_devices(reader: Any, sharing: SharingPolicy = ALL, **tool_input: Any) -> ToolOutput:
    return _call(reader, sharing, tool="list_catalyst_center_devices", **tool_input)


def test_site_devices_are_sorted_and_use_the_site_filter() -> None:
    reader = FakeReader()
    source = _json(_site_devices(reader, site="Global/Berlin"))["sources"][0]

    assert [d["hostname"] for d in source["devices"]] == ["border-1", "edge-1"]
    assert source["total"] == 2 and source["site"] == "Global/Berlin"
    assert source["devices"][0]["management_ip"] == "10.0.0.1"
    sent = reader.devices.filters[0]
    assert sent.sites == ("Global/Berlin",) and sent.include_child_sites is True


def test_site_devices_options_reach_the_filter_and_page() -> None:
    reader = FakeReader()
    only = _json(
        _site_devices(reader, site="Global/Berlin", role="ACCESS", include_child_sites=False)
    )
    page = _json(_site_devices(reader, site="Global/Berlin", limit=1))["sources"][0]

    assert [d["hostname"] for d in only["sources"][0]["devices"]] == ["edge-1"]
    assert reader.devices.filters[0].include_child_sites is False
    assert page["has_more"] is True and len(page["devices"]) == 1


def test_site_devices_hide_addresses_without_the_switch() -> None:
    out = _json(_site_devices(FakeReader(), INVENTORY_ONLY, site="Global/Berlin"))

    assert "management_ip" not in out["sources"][0]["devices"][0]
    assert set(out["withheld_fields"]) == {"management_ip", "serial_number"}


def test_site_devices_need_inventory_and_a_site() -> None:
    reader = FakeReader()

    assert _json(_site_devices(reader, NOTHING, site="x"))["not_shared"] == "inventory_data"
    assert reader.calls == 0
    assert _site_devices(reader).is_error  # site is required


def test_site_devices_errors_are_fixed_and_say_the_right_thing() -> None:
    def failing(error: Exception) -> ToolOutput:
        reader = FakeReader()
        reader.devices.search_error = error
        return _site_devices(reader, site="Global/x")

    unknown = failing(CatalystCenterUnknownSiteError("Unknown site 'x' secret"))
    wide = failing(CatalystCenterTooManySitesError("covers 120 sites secret"))
    many = failing(CatalystCenterTooManyDevicesError(1000))
    other = failing(CatalystCenterValidationError("secret bad id"))
    down = failing(CatalystCenterAPIError("secret https://dnac/x"))

    assert all(o.is_error and "secret" not in o.content for o in (unknown, wide, many, other, down))
    assert "list_catalyst_center_sites" in unknown.content
    assert "too many sub-sites" in wide.content
    assert "more than 1000" in many.content
    # An unrelated validation failure must not tell the model the site is unknown.
    assert "list_catalyst_center_sites" not in other.content and "did not answer" in other.content
    assert "list_catalyst_center_devices" in known_general_tool_names()


def test_fabric_site_filter_reaches_the_service() -> None:
    reader = FakeReader()

    _json(_call(reader, fabric_site=MUNICH))

    assert reader.fabric.sites_asked == [MUNICH]


def test_lists_are_capped_and_rows_come_before_them() -> None:
    many = CatalystCenterFabric(
        sites=tuple(
            CatalystCenterFabricSite(fabric_id=f"f{i}", site_id=f"s{i}", site_name=f"Global/S{i}")
            for i in range(30)
        ),
        devices=FABRIC.devices,
        virtual_networks=tuple(
            CatalystCenterVirtualNetwork(name=f"VN{i}", fabric_sites=(BERLIN,)) for i in range(30)
        ),
    )
    text = _call(FakeReader(FakeFabric(many))).content
    source = json.loads(text)["sources"][0]

    assert source["fabric_site_count"] == 30 and len(source["fabric_sites"]) == 20
    assert source["virtual_network_count"] == 30 and len(source["virtual_networks"]) == 20
    assert text.index('"devices"') < text.index('"virtual_networks"')


def test_incomplete_sites_are_reported() -> None:
    partial = CatalystCenterFabric(
        sites=FABRIC.sites, devices=FABRIC.devices, incomplete_sites=(BERLIN,)
    )
    source = _json(_call(FakeReader(FakeFabric(partial))))["sources"][0]

    assert source["incomplete_sites"] == [BERLIN] and "partial" in source["incomplete_note"]


def test_limit_is_capped_so_a_page_fits_the_tool_output() -> None:
    assert _call(FakeReader(), limit=41).is_error
