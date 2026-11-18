"""get_catalyst_center_device_health and list_catalyst_center_site_health."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from models.catalyst_center import CatalystCenterDevice
from models.catalyst_center_facts import CatalystCenterHealth, CatalystCenterSiteHealth
from services.ai_assistant.catalyst_center_reader import (
    CatalystAccessError,
    CatalystNotConfiguredError,
    CatalystSource,
)
from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.providers.base import ToolCall
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.tools.base import Toolbox, ToolContext, ToolOutput
from services.ai_assistant.tools.catalyst_center_health_tools import (
    build_catalyst_center_health_tools,
)
from services.ai_assistant.tools.catalyst_center_tools import CATALYST_READER_KEY
from services.ai_assistant.tools.playbook_tools import known_general_tool_names
from services.catalyst_center.common.exceptions import (
    CatalystCenterAPIError,
    CatalystCenterNotFoundError,
)

ALL = SharingPolicy(inventory=True, addresses=True, content=True)
INVENTORY_ONLY = SharingPolicy(inventory=True)
NOTHING = SharingPolicy()
LAB = CatalystCenterDevice(
    id="id-lab", hostname="LAB.local.zz", management_ip="10.0.0.1", serial_number="SN-LAB", raw={}
)
LAB2 = CatalystCenterDevice(id="id-lab2", hostname="LAB.other.zz", management_ip="10.0.0.2", raw={})


class FakeDevices:
    def __init__(self, devices=(LAB,)) -> None:
        self.devices = devices

    async def search_devices(self, filters, *, max_devices=None):
        def ok(d):
            if filters.management_ips and d.management_ip not in filters.management_ips:
                return False
            if filters.hostnames:
                return any(
                    h.removesuffix(".*") == (d.hostname or "").split(".")[0]
                    for h in filters.hostnames
                )
            return True

        return tuple(d for d in self.devices if ok(d))


class FakeHealth:
    def __init__(self, error: Exception | None = None) -> None:
        self.error, self.asked = error, []

    async def get_device_health(self, device_id: str):
        self.asked.append(device_id)
        if self.error:
            raise self.error
        return CatalystCenterHealth(
            overall_health=8,
            cpu=12.5,
            memory=40,
            communication_state="REACHABLE",
            maintenance_mode=False,
            timestamp=1_700_000_000_000,
            last_boot_time=0,
        )


def _row(
    name: str, score: float | None, kind: str = "BUILDING", *, total: bool = False
) -> CatalystCenterSiteHealth:
    return CatalystCenterSiteHealth(
        site_name=name,
        is_total=total,
        site_type=kind,
        network_health_average=score,
        number_of_network_devices=3,
        health_switch=score,
    )


class FakeSiteHealth:
    def __init__(self, rows=None, error: Exception | None = None) -> None:
        self.rows = (
            rows
            if rows is not None
            else [
                _row("Munich", 95),
                _row("Berlin", 40),
                _row("Hamburg", None),
                _row("Bonn", 70, "AREA"),
            ]
        )
        self.error, self.site_types = error, []

    async def list_site_health(self, *, site_type=None):
        self.site_types.append(site_type)
        if self.error:
            raise self.error
        return tuple(r for r in self.rows if site_type is None or r.site_type == site_type)


class FakeReader:
    def __init__(self, *, devices=None, health=None, site_health=None, error=None) -> None:
        self.error, self.calls = error, 0
        self.health = health or FakeHealth()
        self.site_health = site_health or FakeSiteHealth()
        self.devices = devices or FakeDevices()

    async def sources(self):
        self.calls += 1
        if self.error:
            raise self.error
        return (
            CatalystSource(
                "lab-dnac",
                self.devices,
                None,
                None,
                self.health,
                self.site_health,  # type: ignore[arg-type]
            ),
        )


def _call(reader: Any, tool: str, sharing: SharingPolicy = ALL, **tool_input: Any) -> ToolOutput:
    ctx = ToolContext(
        user_id=1, redactor=Redactor(), extras={CATALYST_READER_KEY: reader}, sharing=sharing
    )
    box = Toolbox(build_catalyst_center_health_tools(), ctx)
    return asyncio.run(box.execute(ToolCall(id="1", name=tool, input=tool_input)))


def _json(out: ToolOutput) -> dict[str, Any]:
    assert not out.is_error, out.content
    return json.loads(out.content)


def _device(reader: Any, sharing: SharingPolicy = ALL, **kw: Any) -> ToolOutput:
    return _call(reader, "get_catalyst_center_device_health", sharing, **kw)


def _sites(reader: Any, sharing: SharingPolicy = ALL, **kw: Any) -> ToolOutput:
    return _call(reader, "list_catalyst_center_site_health", sharing, **kw)


# -- device health ---------------------------------------------------------------------------


def test_device_health_is_shaped_with_readable_times() -> None:
    reader = FakeReader()
    out = _json(_device(reader, name="LAB"))

    assert out["found"] is True and out["hostname"] == "LAB.local.zz"
    data = out["health"]["data"]
    assert data["overall_health"] == 8 and data["communication_state"] == "REACHABLE"
    assert data["collected_at"] == "2023-11-14T22:13:20Z"
    assert "last_boot" not in data and "timestamp" not in data  # 0 is "unknown", not 1970
    assert reader.health.asked == ["id-lab"]


def test_device_health_lookup_not_found_and_ambiguous() -> None:
    missing = _json(_device(FakeReader(), name="nope"))
    many = _device(FakeReader(devices=FakeDevices((LAB, LAB2))), name="LAB")

    assert missing["found"] is False
    assert many.is_error and "matches 2 devices" in many.content


def test_device_health_gates_send_nothing() -> None:
    reader = FakeReader()

    assert _json(_device(reader, NOTHING, name="LAB"))["not_shared"] == "inventory_data"
    by_ip = _json(_device(reader, INVENTORY_ONLY, management_ip="10.0.0.1"))
    assert by_ip["not_shared"] == "device_addresses"
    assert reader.calls == 0 and reader.health.asked == []
    assert _device(reader).is_error  # a key is required


def test_device_health_failure_is_a_fixed_sentence() -> None:
    reader = FakeReader(health=FakeHealth(CatalystCenterAPIError("secret https://dnac/x")))
    out = _json(_device(reader, name="LAB"))

    assert "secret" not in json.dumps(out) and "error" in out["health"]


# -- site health -----------------------------------------------------------------------------


def test_sites_worst_first_and_unscored_last() -> None:
    out = _json(_sites(FakeReader()))["sources"][0]

    assert [s["site_name"] for s in out["sites"]] == ["Berlin", "Bonn", "Munich", "Hamburg"]
    assert out["total"] == 4 and "network_health_average" not in out["sites"][-1]


def test_sites_filters_page_and_site_type() -> None:
    reader = FakeReader()
    unhealthy = _json(_sites(reader, max_network_health=70))["sources"][0]
    named = _json(_sites(reader, name_contains="MUN"))["sources"][0]
    page = _json(_sites(reader, limit=1, offset=1))["sources"][0]
    _json(_sites(reader, site_type="AREA"))

    assert [s["site_name"] for s in unhealthy["sites"]] == ["Berlin", "Bonn"]  # no score: left out
    assert [s["site_name"] for s in named["sites"]] == ["Munich"]
    assert page["has_more"] is True and [s["site_name"] for s in page["sites"]] == ["Bonn"]
    assert reader.site_health.site_types[-1] == "AREA"


def test_sites_need_inventory_and_report_errors_as_sentences() -> None:
    reader = FakeReader()
    assert _json(_sites(reader, NOTHING))["not_shared"] == "inventory_data" and reader.calls == 0

    missing = _sites(FakeReader(site_health=FakeSiteHealth(error=CatalystCenterNotFoundError("x"))))
    failed = _sites(FakeReader(site_health=FakeSiteHealth(error=CatalystCenterAPIError("secret"))))
    assert missing.is_error and "site health API" in missing.content
    assert failed.is_error and "secret" not in failed.content


def test_no_source_no_access_input_and_registration() -> None:
    assert (
        "No Cisco Catalyst Center source"
        in _sites(FakeReader(error=CatalystNotConfiguredError())).content
    )
    assert (
        "cannot read Catalyst Center"
        in _device(FakeReader(error=CatalystAccessError()), name="LAB").content
    )
    assert _sites(FakeReader(), site_type="CAMPUS").is_error
    assert _sites(FakeReader(), site_type="FLOOR").is_error  # not a /site-health type
    assert _sites(FakeReader(), limit=51).is_error  # a page must fit the tool output
    names = known_general_tool_names()
    assert {"get_catalyst_center_device_health", "list_catalyst_center_site_health"} <= names


def test_aggregate_rows_are_not_sites_but_come_back_as_overall() -> None:
    reader = FakeReader(
        site_health=FakeSiteHealth(
            [_row("All Sites", 100, "area", total=True), _row("Berlin", 40), _row("Bonn", 70)]
        )
    )
    source = _json(_sites(reader))["sources"][0]

    assert [s["site_name"] for s in source["sites"]] == ["Berlin", "Bonn"]
    assert source["total"] == 2  # the total row is not a site
    assert [o["site_name"] for o in source["overall"]] == ["All Sites"]
    assert "is_total" not in source["overall"][0]
    assert source["sites"][0]["health_switch"] == 40  # the switch score is passed on

    # A narrowed or paged question is about sites only: no overall block.
    assert "overall" not in _json(_sites(reader, max_network_health=50))["sources"][0]
    assert "overall" not in _json(_sites(reader, name_contains="Ber"))["sources"][0]
    assert "overall" not in _json(_sites(reader, offset=1))["sources"][0]


def test_a_name_search_for_the_aggregate_returns_it_as_overall() -> None:
    reader = FakeReader(
        site_health=FakeSiteHealth([_row("All Sites", 100, "area", total=True), _row("Berlin", 40)])
    )
    source = _json(_sites(reader, name_contains="all sites"))["sources"][0]

    assert source["sites"] == []
    assert [o["site_name"] for o in source["overall"]] == ["All Sites"]
