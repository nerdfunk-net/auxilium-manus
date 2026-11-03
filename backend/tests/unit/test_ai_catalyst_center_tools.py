"""Catalyst Center tools for Ask the Net: lookup, gates, errors, redaction, wiring."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any
from unittest.mock import MagicMock, patch

from models.catalyst_center import CatalystCenterDevice
from models.catalyst_center_facts import (
    CatalystCenterCompliance,
    CatalystCenterComplianceItem,
    CatalystCenterDeviceDetails,
    CatalystCenterInterface,
    CatalystCenterSoftware,
    CatalystCenterVlan,
)
from services.ai_assistant import catalyst_center_reader as reader_module
from services.ai_assistant.catalyst_center_reader import (
    CatalystAccessError,
    CatalystNotConfiguredError,
    CatalystSource,
    CatalystSourcesUnusableError,
    DbCatalystCenterReader,
)
from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.providers.base import ToolCall
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.results.store import InMemoryResultBackend, ResultStore
from services.ai_assistant.surfaces import build_general_session
from services.ai_assistant.tools.base import Toolbox, ToolContext, ToolOutput
from services.ai_assistant.tools.catalyst_center_tools import (
    CATALYST_READER_KEY,
    build_catalyst_center_tools,
)
from services.ai_assistant.tools.playbook_tools import known_general_tool_names
from services.catalyst_center.common.exceptions import (
    CatalystCenterAPIError,
    CatalystCenterTooManyDevicesError,
)
from services.catalyst_center.credentials import CatalystCenterCredentials
from tests.unit.test_ai_batfish_tools import FakeReader

ALL = SharingPolicy(inventory=True, addresses=True, content=True)
INVENTORY_ONLY = SharingPolicy(inventory=True)
NOTHING = SharingPolicy()
SECRET = "hunter2hunter2"


def _device(hostname: str, device_id: str, ip: str, serial: str) -> CatalystCenterDevice:
    return CatalystCenterDevice(
        id=device_id,
        hostname=hostname,
        management_ip=ip,
        serial_number=serial,
        role="ACCESS",
        family="Switches and Hubs",
        device_type="Cisco Catalyst 9300",
        platform_id="C9300-24P",
        software_version="17.9.4",
        reachability_status="Reachable",
        collection_status="Managed",
        mac_address="aa:bb:cc:dd:ee:ff",
        raw={"never": "shown"},
    )


LAB = _device("LAB.local.zz", "id-lab", "10.0.0.1", "SN-LAB")
LAB2 = _device("LAB2.local.zz", "id-lab2", "10.0.0.2", "SN-LAB2")
OTHER = _device("core-1.local.zz", "id-core", "10.0.0.9", "SN-CORE")
LAB_UPPER = _device("LAB.other.zz", "id-lab-other", "10.9.0.1", "SN-LABO")


class FakeDevices:
    """Behaves like the controller: case-sensitive full-string match, ``.*`` is a wildcard."""

    def __init__(self, devices: list[CatalystCenterDevice]) -> None:
        self.devices = devices
        self.filters: list[Any] = []

    async def search_devices(self, filters: Any, *, max_devices: int | None = None):
        self.filters.append(filters)
        found = [d for d in self.devices if self._matches(filters, d)]
        if max_devices is not None and len(found) > max_devices:
            raise CatalystCenterTooManyDevicesError(max_devices)
        return tuple(found)

    @staticmethod
    def _matches(filters: Any, device: CatalystCenterDevice) -> bool:
        if filters.hostnames and not any(
            re.fullmatch(pattern, device.hostname or "") for pattern in filters.hostnames
        ):
            return False
        if filters.management_ips and device.management_ip not in filters.management_ips:
            return False
        return not filters.serial_numbers or device.serial_number in filters.serial_numbers


class FakeDetails:
    def __init__(self, *, fail: frozenset[str] = frozenset(), interfaces: int = 2) -> None:
        self.fail = fail
        self.calls: list[tuple[str, str]] = []
        self._interfaces = interfaces

    def _enter(self, fact: str, device_id: str) -> None:
        self.calls.append((fact, device_id))
        if fact in self.fail:
            raise CatalystCenterAPIError(f"upstream said {SECRET} at https://dnac.internal/x")

    async def get_device_and_software(self, device_id: str):
        self._enter("device", device_id)
        return (
            CatalystCenterDeviceDetails(
                id=device_id,
                hostname="LAB.local.zz",
                management_ip="10.0.0.1",
                serial_number="SN-LAB",
                mac_address="aa:bb:cc:dd:ee:ff",
                role="ACCESS",
                reachability_status="Reachable",
                up_time="12 days",
                location_name="Global/Berlin",
            ),
            CatalystCenterSoftware(
                software_type="IOS-XE",
                software_version="17.9.4",
                series="C9300",
                description="Cisco IOS XE; contact ops-secret",
            ),
        )

    async def get_interfaces(self, device_id: str):
        self._enter("interfaces", device_id)
        return tuple(
            CatalystCenterInterface(
                name=f"GigabitEthernet1/0/{n}",
                description="uplink to core",
                status="up",
                speed="1000000",
                ipv4_address=f"10.1.{n}.1",
                ipv4_mask="255.255.255.0",
                mac_address="aa:bb:cc:00:00:0" + str(n),
            )
            for n in range(1, self._interfaces + 1)
        )

    async def get_vlans(self, device_id: str):
        self._enter("vlans", device_id)
        return (CatalystCenterVlan(vlan_number=10, interface_name="Vlan10", ip_address="10.2.0.1"),)

    async def get_compliance(self, device_id: str):
        self._enter("compliance", device_id)
        return CatalystCenterCompliance(
            status="COMPLIANT",
            items=(CatalystCenterComplianceItem(compliance_type="IMAGE", status="COMPLIANT"),),
        )


class FakeCatalystReader:
    def __init__(self, sources: tuple[CatalystSource, ...] | None = None, error=None) -> None:
        self.error = error
        self.calls = 0
        self._sources = (
            sources
            if sources is not None
            else (CatalystSource("lab-dnac", FakeDevices([LAB, LAB2, OTHER]), FakeDetails()),)
        )

    async def sources(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self._sources


def _box(reader: Any, sharing: SharingPolicy = ALL, secrets: tuple[str, ...] = ()) -> Toolbox:
    redactor = Redactor()
    redactor.add_known_secrets(secrets)
    ctx = ToolContext(
        user_id=1, redactor=redactor, extras={CATALYST_READER_KEY: reader}, sharing=sharing
    )
    return Toolbox(build_catalyst_center_tools(), ctx)


def _call(box: Toolbox, tool: str, /, **tool_input: Any) -> ToolOutput:
    # Positional-only: a tool input may itself be called ``name``.
    return asyncio.run(box.execute(ToolCall(id="1", name=tool, input=tool_input)))


def _json(out: ToolOutput) -> dict[str, Any]:
    assert not out.is_error, out.content
    return json.loads(out.content)


# -- find_catalyst_center_device -------------------------------------------------------------


def test_find_by_name_tries_the_usual_spellings_in_one_request() -> None:
    reader = FakeCatalystReader()
    out = _json(_call(_box(reader), "find_catalyst_center_device", name="lab"))

    # A controller matches case-sensitively, so one request carries every spelling.
    sent = reader._sources[0].devices.filters[0].hostnames
    assert {"lab", "lab.*", "LAB", "LAB.*", "Lab", "Lab.*"} <= set(sent)
    assert [m["hostname"] for m in out["matches"]] == ["LAB.local.zz"]
    assert out["matches"][0]["source_id"] == "lab-dnac"
    assert out["matches"][0]["id"] == "id-lab"


def test_a_short_name_does_not_match_a_longer_one() -> None:
    out = _json(_call(_box(FakeCatalystReader()), "find_catalyst_center_device", name="LAB"))

    assert "LAB2.local.zz" not in {m["hostname"] for m in out["matches"]}


def test_find_by_management_ip_and_by_serial() -> None:
    box = _box(FakeCatalystReader())

    by_ip = _json(_call(box, "find_catalyst_center_device", management_ip="10.0.0.9"))
    by_serial = _json(_call(box, "find_catalyst_center_device", serial_number="SN-LAB2"))

    assert [m["hostname"] for m in by_ip["matches"]] == ["core-1.local.zz"]
    assert [m["hostname"] for m in by_serial["matches"]] == ["LAB2.local.zz"]


def test_not_found_is_an_answer_not_an_error() -> None:
    out = _json(_call(_box(FakeCatalystReader()), "find_catalyst_center_device", name="nope"))

    assert out["matches"] == []
    assert "not found in Catalyst Center" in out["message"]


def test_a_lookup_needs_at_least_one_key() -> None:
    out = _call(_box(FakeCatalystReader()), "find_catalyst_center_device")

    assert out.is_error and "name, management_ip or serial_number" in out.content


def test_a_bad_ip_is_refused_before_any_request() -> None:
    reader = FakeCatalystReader()
    out = _call(_box(reader), "find_catalyst_center_device", management_ip="not-an-ip")

    assert out.is_error and reader.calls == 0


def test_unknown_input_fields_are_refused() -> None:
    out = _call(_box(FakeCatalystReader()), "find_catalyst_center_device", name="a", site="x")

    assert out.is_error and "Invalid input" in out.content


# -- no source / no access -------------------------------------------------------------------


def test_no_configured_source_tells_the_model_to_tell_the_user() -> None:
    reader = FakeCatalystReader(error=CatalystNotConfiguredError())
    for tool in ("find_catalyst_center_device", "get_catalyst_center_device_details"):
        out = _call(_box(reader), tool, name="LAB")

        assert out.is_error
        assert "No Cisco Catalyst Center source is configured" in out.content
        assert "tell the user" in out.content.lower()


def test_missing_permission_is_reported() -> None:
    out = _call(
        _box(FakeCatalystReader(error=CatalystAccessError())),
        "find_catalyst_center_device",
        name="LAB",
    )

    assert out.is_error and "cannot read Catalyst Center" in out.content


def test_a_failing_controller_gives_a_fixed_sentence_never_upstream_text() -> None:
    class Broken(FakeDevices):
        async def search_devices(self, filters, *, max_devices=None):
            raise CatalystCenterAPIError(f"{SECRET} https://dnac.internal/token")

    reader = FakeCatalystReader((CatalystSource("lab-dnac", Broken([]), FakeDetails()),))
    out = _call(_box(reader, secrets=(SECRET,)), "find_catalyst_center_device", name="LAB")

    assert out.is_error
    assert SECRET not in out.content and "dnac.internal" not in out.content
    assert "lab-dnac" in out.content


def test_one_broken_source_does_not_hide_a_match_in_another() -> None:
    class Broken(FakeDevices):
        async def search_devices(self, filters, *, max_devices=None):
            raise CatalystCenterAPIError("down")

    reader = FakeCatalystReader(
        (
            CatalystSource("down", Broken([]), FakeDetails()),
            CatalystSource("up", FakeDevices([LAB]), FakeDetails()),
        )
    )
    out = _json(_call(_box(reader), "find_catalyst_center_device", name="LAB"))

    assert [m["source_id"] for m in out["matches"]] == ["up"]
    assert out["source_errors"][0]["source_id"] == "down"


# -- gates -----------------------------------------------------------------------------------


def test_without_the_inventory_switch_nothing_is_sent() -> None:
    reader = FakeCatalystReader()
    box = _box(reader, NOTHING)
    for tool in ("find_catalyst_center_device", "get_catalyst_center_device_details"):
        out = _call(box, tool, name="LAB")

        assert not out.is_error and "not_shared" in out.content
    assert reader.calls == 0


def test_lookup_by_address_or_serial_needs_the_addresses_switch() -> None:
    reader = FakeCatalystReader()
    box = _box(reader, INVENTORY_ONLY)

    by_ip = _call(box, "find_catalyst_center_device", management_ip="10.0.0.1")
    by_serial = _call(box, "get_catalyst_center_device_details", serial_number="SN-LAB")

    assert "not_shared" in by_ip.content and "not_shared" in by_serial.content
    assert reader.calls == 0


def test_find_withholds_addresses_and_serials_without_the_switch() -> None:
    box = _box(FakeCatalystReader(), INVENTORY_ONLY)
    out = _json(_call(box, "find_catalyst_center_device", name="LAB"))

    match = out["matches"][0]
    assert "management_ip" not in match and "serial_number" not in match
    assert "mac_address" not in match
    assert set(out["withheld_fields"]) >= {"management_ip", "serial_number"}
    assert "raw" not in match


def test_find_with_the_addresses_switch_shows_them_but_never_the_raw_payload() -> None:
    match = _json(_call(_box(FakeCatalystReader()), "find_catalyst_center_device", name="LAB"))[
        "matches"
    ][0]

    assert match["management_ip"] == "10.0.0.1" and match["serial_number"] == "SN-LAB"
    assert "raw" not in match and "never" not in json.dumps(match)


# -- get_catalyst_center_device_details ------------------------------------------------------


def test_details_default_to_device_and_software() -> None:
    reader = FakeCatalystReader()
    out = _json(_call(_box(reader), "get_catalyst_center_device_details", name="LAB"))

    assert out["source_id"] == "lab-dnac" and out["hostname"] == "LAB.local.zz"
    assert out["facts"]["device"]["data"]["up_time"] == "12 days"
    assert out["facts"]["software"]["data"]["software_version"] == "17.9.4"
    assert set(out["facts"]) == {"device", "software"}
    assert reader._sources[0].details.calls == [("device", "id-lab")]


def test_details_with_every_fact() -> None:
    out = _json(
        _call(
            _box(FakeCatalystReader()),
            "get_catalyst_center_device_details",
            name="LAB",
            facts=["device", "software", "interfaces", "vlans", "compliance"],
        )
    )

    assert out["facts"]["vlans"]["data"][0]["vlan_number"] == 10
    assert out["facts"]["compliance"]["data"]["status"] == "COMPLIANT"
    assert out["facts"]["compliance"]["data"]["items"][0]["compliance_type"] == "IMAGE"
    assert out["facts"]["interfaces"]["data"]["total"] == 2


def test_unknown_fact_names_are_refused() -> None:
    out = _call(
        _box(FakeCatalystReader()), "get_catalyst_center_device_details", name="LAB", facts=["x"]
    )

    assert out.is_error and "Invalid input" in out.content


def test_details_withhold_addresses_and_descriptions_by_switch() -> None:
    facts = ["device", "interfaces", "vlans"]
    inventory = _json(
        _call(
            _box(FakeCatalystReader(), INVENTORY_ONLY),
            "get_catalyst_center_device_details",
            name="LAB",
            facts=facts,
        )
    )
    addresses = _json(
        _call(
            _box(FakeCatalystReader(), SharingPolicy(inventory=True, addresses=True)),
            "get_catalyst_center_device_details",
            name="LAB",
            facts=facts,
        )
    )

    dump = json.dumps(inventory["facts"])
    assert "10.0.0.1" not in dump and "SN-LAB" not in dump and "10.1.1.1" not in dump
    assert "aa:bb:cc" not in dump and "uplink to core" not in dump
    assert set(inventory["withheld_fields"]) >= {
        "management_ip",
        "serial_number",
        "ipv4_address",
        "description",
        "ip_address",
    }
    adr = json.dumps(addresses["facts"])
    assert "10.0.0.1" in adr and "10.1.1.1" in adr and "10.2.0.1" in adr
    assert "uplink to core" not in adr  # free text needs the content switch
    assert "description" in addresses["withheld_fields"]


def test_details_with_the_content_switch_show_interface_descriptions() -> None:
    out = _json(
        _call(
            _box(FakeCatalystReader()),
            "get_catalyst_center_device_details",
            name="LAB",
            facts=["interfaces"],
        )
    )

    assert out["facts"]["interfaces"]["data"]["items"][0]["description"] == "uplink to core"
    assert "withheld_fields" not in out


def test_one_failing_fact_does_not_hide_the_others_and_leaks_no_upstream_text() -> None:
    reader = FakeCatalystReader(
        (CatalystSource("lab-dnac", FakeDevices([LAB]), FakeDetails(fail=frozenset({"vlans"}))),)
    )
    out = _json(
        _call(
            _box(reader, secrets=(SECRET,)),
            "get_catalyst_center_device_details",
            name="LAB",
            facts=["device", "vlans"],
        )
    )

    assert out["facts"]["device"]["data"]["role"] == "ACCESS"
    assert "error" in out["facts"]["vlans"] and "data" not in out["facts"]["vlans"]
    assert SECRET not in json.dumps(out) and "dnac.internal" not in json.dumps(out)


def test_interfaces_are_paged_and_filtered() -> None:
    reader = FakeCatalystReader(
        (CatalystSource("lab-dnac", FakeDevices([LAB]), FakeDetails(interfaces=30)),)
    )
    box = _box(reader)
    page = _json(
        _call(
            box,
            "get_catalyst_center_device_details",
            name="LAB",
            facts=["interfaces"],
            interface_limit=10,
            interface_offset=5,
        )
    )["facts"]["interfaces"]["data"]
    narrowed = _json(
        _call(
            box,
            "get_catalyst_center_device_details",
            name="LAB",
            facts=["interfaces"],
            interface_name_contains="1/0/30",
        )
    )["facts"]["interfaces"]["data"]

    assert page["total"] == 30 and page["has_more"] is True and len(page["items"]) == 10
    assert page["items"][0]["name"] == "GigabitEthernet1/0/6"
    assert [i["name"] for i in narrowed["items"]] == ["GigabitEthernet1/0/30"]
    assert narrowed["total"] == 1


def test_an_ambiguous_name_lists_the_candidates_and_reads_nothing() -> None:
    details = FakeDetails()
    reader = FakeCatalystReader(
        (CatalystSource("lab-dnac", FakeDevices([LAB, LAB_UPPER]), details),)
    )
    out = _call(_box(reader), "get_catalyst_center_device_details", name="LAB")

    assert out.is_error
    assert "LAB.local.zz" in out.content and "LAB.other.zz" in out.content
    assert details.calls == []


def test_a_device_missing_from_catalyst_center_is_not_an_error() -> None:
    out = _json(_call(_box(FakeCatalystReader()), "get_catalyst_center_device_details", name="zzz"))

    assert out["found"] is False and "not found in Catalyst Center" in out["message"]


def test_secrets_are_redacted_in_results() -> None:
    device = _device(f"sw-{SECRET}.zz", "id-s", "10.0.0.5", "SN-S")
    reader = FakeCatalystReader((CatalystSource("lab-dnac", FakeDevices([device]), FakeDetails()),))
    box = _box(reader, secrets=(SECRET,))
    out = _call(box, "find_catalyst_center_device", name=f"sw-{SECRET}.zz")

    assert SECRET not in out.content


# -- the reader ------------------------------------------------------------------------------

CREDS = CatalystCenterCredentials(base_url="https://dnac", username="u", password="p")


def _load(allowed: bool, rows: list[dict[str, Any]], resolve) -> Any:
    reader = DbCatalystCenterReader(user_id=5)
    config = MagicMock()
    config.list_sources.return_value = rows
    config.resolve_credentials.side_effect = resolve
    rbac = MagicMock()
    rbac.has_permission.return_value = allowed
    with (
        patch.object(reader_module, "SessionLocal"),
        patch.object(reader_module, "RBACService", return_value=rbac),
        patch.object(
            reader_module.service_factory,
            "build_catalyst_center_source_config_service",
            return_value=config,
        ),
        patch.object(reader_module.service_factory, "build_catalyst_center_device_service"),
        patch.object(reader_module.service_factory, "build_catalyst_center_details_service"),
    ):
        try:
            return asyncio.run(reader.sources()), rbac
        except (
            CatalystAccessError,
            CatalystNotConfiguredError,
            CatalystSourcesUnusableError,
        ) as exc:
            return exc, rbac


def test_the_reader_checks_the_source_permission_on_every_call() -> None:
    result, rbac = _load(False, [{"source_id": "a"}], lambda _id: CREDS)

    assert isinstance(result, CatalystAccessError)
    rbac.has_permission.assert_called_once_with(5, "sources.catalyst_center", "read")


def test_the_reader_reports_no_source() -> None:
    result, _ = _load(True, [], lambda _id: CREDS)

    assert isinstance(result, CatalystNotConfiguredError)


def test_the_reader_returns_every_usable_source_and_skips_a_broken_one(caplog) -> None:
    def resolve(source_id: str):
        if source_id == "bad":
            raise RuntimeError(f"cannot decrypt {SECRET}")
        return CREDS

    with caplog.at_level("WARNING", logger=reader_module.logger.name):
        result, _ = _load(True, [{"source_id": "bad"}, {"source_id": "good"}], resolve)

    assert [s.source_id for s in result] == ["good"]
    assert "RuntimeError" in caplog.text and SECRET not in caplog.text


def test_the_reader_with_only_broken_sources_says_unusable_not_missing() -> None:
    def resolve(_id: str):
        raise RuntimeError("boom")

    result, _ = _load(True, [{"source_id": "bad"}], resolve)

    assert isinstance(result, CatalystSourcesUnusableError)
    assert not isinstance(result, CatalystNotConfiguredError)


def test_the_reader_never_logs_the_error_text_even_at_debug(caplog) -> None:
    def resolve(_id: str):
        raise RuntimeError(f"cannot decrypt {SECRET}")

    with caplog.at_level("DEBUG", logger=reader_module.logger.name):
        _load(True, [{"source_id": "bad"}], resolve)

    assert SECRET not in caplog.text
    assert all(r.exc_info is None for r in caplog.records)


def test_unusable_sources_are_not_reported_as_missing_to_the_user() -> None:
    reader = FakeCatalystReader(error=CatalystSourcesUnusableError())
    out = _call(_box(reader), "find_catalyst_center_device", name="LAB")

    assert out.is_error and "none is usable" in out.content
    assert "add one" not in out.content


# -- the general surface ---------------------------------------------------------------------


def _session(**overrides: Any):
    base: dict[str, Any] = {
        "user_id": 7,
        "reader": FakeReader(),
        "store": ResultStore(InMemoryResultBackend()),
        "sharing": ALL,
        "may_query_batfish": True,
        "catalyst_reader": FakeCatalystReader(),
    }
    base.update(overrides)
    return build_general_session(**base)


def test_the_surface_offers_the_catalyst_tools_and_the_prompt() -> None:
    session = _session()
    names = {s.name for s in session.toolbox.specs()}

    assert {"find_catalyst_center_device", "get_catalyst_center_device_details"} <= names
    assert "Catalyst Center" in session.system


def test_the_surface_without_a_reader_has_no_catalyst_tools() -> None:
    session = _session(catalyst_reader=None)

    assert not {s.name for s in session.toolbox.specs()} & {
        "find_catalyst_center_device",
        "get_catalyst_center_device_details",
    }
    assert "Catalyst Center" not in session.system


def test_catalyst_tools_work_without_batfish() -> None:
    session = _session(may_query_batfish=False)

    assert "find_catalyst_center_device" in {s.name for s in session.toolbox.specs()}
    assert "only the" in session.system and "Catalyst Center" in session.system


def test_playbooks_may_name_the_catalyst_tools() -> None:
    assert {"find_catalyst_center_device", "get_catalyst_center_device_details"} <= (
        known_general_tool_names()
    )


def test_the_prompt_tells_the_model_to_check_nautobot_first() -> None:
    system = _session().system

    assert "Nautobot" in system and "find_catalyst_center_device" in system


# -- gaps found by mutation checks -----------------------------------------------------------


def test_redaction_runs_before_json_encoding() -> None:
    # A quote is escaped by json.dumps, so the toolbox's pass over the text would miss it.
    secret = 'pa"ssword-12345'
    device = _device(f"sw-{secret}", "id-q", "10.0.0.7", "SN-Q")
    reader = FakeCatalystReader((CatalystSource("lab-dnac", FakeDevices([device]), FakeDetails()),))
    box = _box(reader, secrets=(secret,))

    out = _call(box, "find_catalyst_center_device", management_ip="10.0.0.7")

    assert secret not in json.loads(out.content)["matches"][0]["hostname"]


def test_a_field_added_to_a_fact_model_is_not_shown_until_a_rule_names_it() -> None:
    class Wider(CatalystCenterDeviceDetails):
        internal_note: str | None = None

    class WiderDetails(FakeDetails):
        async def get_device_and_software(self, device_id: str):
            device, software = await super().get_device_and_software(device_id)
            return Wider(**device.model_dump(), internal_note="do-not-leak"), software

    reader = FakeCatalystReader((CatalystSource("lab-dnac", FakeDevices([LAB]), WiderDetails()),))
    out = _call(_box(reader), "get_catalyst_center_device_details", name="LAB")

    assert "do-not-leak" not in out.content


# -- review findings (doc/analysis/REVIEW.md) ------------------------------------------------


def _reader_of(*devices: CatalystCenterDevice, details: FakeDetails | None = None):
    fake = FakeDevices(list(devices))
    return FakeCatalystReader((CatalystSource("lab-dnac", fake, details or FakeDetails()),)), fake


def test_a_mixed_case_hostname_is_found_by_the_inventory_scan() -> None:
    mixed = _device("Lab-SW1.Local.zz", "id-mixed", "10.0.0.20", "SN-MIXED")
    reader, fake = _reader_of(mixed, OTHER)

    out = _json(_call(_box(reader), "find_catalyst_center_device", name="lab-sw1"))

    assert [m["hostname"] for m in out["matches"]] == ["Lab-SW1.Local.zz"]
    # The targeted query missed; the second request read the whole inventory.
    assert len(fake.filters) == 2 and not fake.filters[1].hostnames


def test_a_hit_of_the_targeted_query_needs_no_scan() -> None:
    reader, fake = _reader_of(LAB, OTHER)

    _json(_call(_box(reader), "find_catalyst_center_device", name="LAB"))

    assert len(fake.filters) == 1


def test_the_scan_does_not_match_a_longer_name_in_another_case() -> None:
    reader, _ = _reader_of(_device("Lab2.local.zz", "id-2", "10.0.0.21", "SN-2"))

    out = _json(_call(_box(reader), "find_catalyst_center_device", name="LAB"))

    assert out["matches"] == []


def test_too_many_wildcard_hits_still_fall_back_to_the_scan() -> None:
    many = [
        _device(f"LAB{n}.local.zz", f"id-{n}", f"10.5.0.{n % 250}", f"SN-{n}") for n in range(210)
    ]
    reader, _ = _reader_of(*many, _device("LAB.local.zz", "id-real", "10.0.0.1", "SN-LAB"))

    out = _json(_call(_box(reader), "find_catalyst_center_device", name="LAB"))

    assert [m["id"] for m in out["matches"]] == ["id-real"]


def test_the_device_behind_many_wildcard_hits_is_not_reported_missing() -> None:
    # 12 devices named LAB<n> fill any window; the real LAB must still be found.
    noise = [_device(f"LAB{n}.local.zz", f"id-n{n}", f"10.6.0.{n}", f"SN-N{n}") for n in range(12)]
    reader, _ = _reader_of(*noise, LAB)

    out = _json(_call(_box(reader), "find_catalyst_center_device", name="LAB"))

    assert [m["hostname"] for m in out["matches"]] == ["LAB.local.zz"]
    assert "has_more" not in out and "message" not in out


def test_details_read_the_one_confirmed_device_among_wildcard_noise() -> None:
    noise = [_device(f"LAB{n}.local.zz", f"id-n{n}", f"10.6.0.{n}", f"SN-N{n}") for n in range(12)]
    details = FakeDetails()
    reader, _ = _reader_of(*noise, LAB, details=details)

    out = _json(_call(_box(reader), "get_catalyst_center_device_details", name="LAB"))

    assert out["device_id"] == "id-lab" and details.calls == [("device", "id-lab")]


def test_eleven_matches_report_has_more_and_keep_ten() -> None:
    same_ip = [_device(f"d{n:02d}.zz", f"id-{n:02d}", "10.8.0.1", f"SN-{n}") for n in range(11)]
    reader, _ = _reader_of(*reversed(same_ip))

    out = _json(_call(_box(reader), "find_catalyst_center_device", management_ip="10.8.0.1"))

    assert out["has_more"] is True
    assert [m["hostname"] for m in out["matches"]] == [f"d{n:02d}.zz" for n in range(10)]


def test_several_sources_are_merged_in_a_fixed_order() -> None:
    a = CatalystSource(
        "a-dnac", FakeDevices([_device("x.zz", "id-a", "10.9.1.1", "S1")]), FakeDetails()
    )
    b = CatalystSource(
        "b-dnac", FakeDevices([_device("x.zz", "id-b", "10.9.1.1", "S2")]), FakeDetails()
    )

    for order in ((a, b), (b, a)):
        out = _json(
            _call(
                _box(FakeCatalystReader(order)),
                "find_catalyst_center_device",
                management_ip="10.9.1.1",
            )
        )
        assert [m["source_id"] for m in out["matches"]] == ["a-dnac", "b-dnac"]


def test_lookup_keys_are_alternatives_not_a_conjunction() -> None:
    reader, _ = _reader_of(LAB, OTHER)
    box = _box(reader)

    # A stale IP from Nautobot must not hide a device the name finds ...
    stale = _json(_call(box, "find_catalyst_center_device", name="LAB", management_ip="192.0.2.99"))
    # ... and the most specific key that finds something decides.
    serial_wins = _json(
        _call(box, "find_catalyst_center_device", name="LAB", serial_number="SN-CORE")
    )

    assert [m["hostname"] for m in stale["matches"]] == ["LAB.local.zz"]
    assert [m["hostname"] for m in serial_wins["matches"]] == ["core-1.local.zz"]


def test_two_keys_that_find_nothing_say_not_found() -> None:
    reader, _ = _reader_of(LAB)

    out = _json(
        _call(_box(reader), "find_catalyst_center_device", name="nope", serial_number="SN-NONE")
    )

    assert out["matches"] == [] and "not found in Catalyst Center" in out["message"]


def test_keys_with_an_address_still_need_the_addresses_switch() -> None:
    reader, _ = _reader_of(LAB)

    out = _call(
        _box(reader, INVENTORY_ONLY), "find_catalyst_center_device", name="LAB", serial_number="X"
    )

    assert "not_shared" in out.content and reader.calls == 0


def test_the_software_description_is_free_text_and_needs_the_content_switch() -> None:
    reader, _ = _reader_of(LAB)
    withheld = _json(
        _call(
            _box(reader, SharingPolicy(inventory=True, addresses=True)),
            "get_catalyst_center_device_details",
            name="LAB",
        )
    )
    shared = _json(_call(_box(reader), "get_catalyst_center_device_details", name="LAB"))

    assert "ops-secret" not in json.dumps(withheld)
    assert "description" in withheld["withheld_fields"]
    assert withheld["facts"]["software"]["data"]["software_version"] == "17.9.4"
    assert shared["facts"]["software"]["data"]["description"] == "Cisco IOS XE; contact ops-secret"


def test_a_controller_with_too_many_devices_for_the_scan_is_a_source_error() -> None:
    class Huge(FakeDevices):
        async def search_devices(self, filters, *, max_devices=None):
            if not filters.hostnames:
                raise CatalystCenterTooManyDevicesError(max_devices or 0)
            return ()

    reader = FakeCatalystReader((CatalystSource("big", Huge([]), FakeDetails()),))
    out = _call(_box(reader), "find_catalyst_center_device", name="LAB")

    assert out.is_error and "management IP or serial" in out.content
