"""ACI device tools for Ask the Net: lookup, gates, errors, field rules, wiring."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from models import aci_facts
from models.aci import AciDevice
from models.aci_facts import AciDeviceDetails, AciInterface, AciSoftware
from services.aci.common.exceptions import AciAPIError, AciAuthError
from services.ai_assistant.aci_reader import (
    AciAccessError,
    AciNotConfiguredError,
    AciSource,
    AciSourcesUnusableError,
)
from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.providers.base import ToolCall
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.results.store import InMemoryResultBackend, ResultStore
from services.ai_assistant.surfaces import build_general_session
from services.ai_assistant.tools import aci_fields, aci_tools
from services.ai_assistant.tools.aci_tools import ACI_READER_KEY, build_aci_tools
from services.ai_assistant.tools.base import Toolbox, ToolContext, ToolOutput
from services.ai_assistant.tools.playbook_tools import known_general_tool_names
from tests.unit.test_ai_batfish_tools import FakeReader
from workflow_steps.get_aci_details.executor import FACTS

ALL = SharingPolicy(inventory=True, addresses=True, content=True)
INVENTORY_ONLY = SharingPolicy(inventory=True)
NOTHING = SharingPolicy()
SECRET = "hunter2hunter2"


def _device(node: int, name: str, role: str = "leaf", serial: str = "SN") -> AciDevice:
    return AciDevice(
        node_id=node,
        name=name,
        role=role,  # type: ignore[arg-type]
        pod_id=1,
        model="N9K-C93180YC-FX",
        serial_number=f"{serial}{node}",
        software_version="n9000-16.1(4h)",
        fabric_state="active",
        system_state="in-service",
        tep_address="10.0.8.65",
        management_ip=f"192.0.2.{node}",
        dn=f"topology/pod-1/node-{node}",
        raw={"never": "shown"},
    )


LEAF1 = _device(101, "leaf-101")
LEAF2 = _device(102, "leaf-102")
SPINE = _device(201, "spine-201", role="spine")


class FakeDevices:
    def __init__(self, devices: list[AciDevice], error: Exception | None = None) -> None:
        self.devices = devices
        self.error = error
        self.calls = 0

    async def search(self, filters: Any = None, *, max_devices: int | None = None):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return list(self.devices)


class FakeDetails:
    def __init__(self, fail: set[str] | None = None) -> None:
        self.fail = fail or set()
        self.calls: list[str] = []

    async def get_device_and_software(self, pod: int, node: int):
        self.calls.append("device")
        return (
            AciDeviceDetails(
                node_id=node, name="leaf-101", serial_number="SN101", tep_address="10.0.8.65"
            ),
            AciSoftware(software_version="16.1(4h)"),
        )

    async def get_interfaces(self, pod: int, node: int):
        self.calls.append("interfaces")
        if "interfaces" in self.fail:
            raise AciAPIError(f"boom {SECRET}")
        return tuple(
            AciInterface(
                name=f"eth1/{i}",
                kind="physical",
                description=f"uplink {SECRET}",
                mac_address="aa:bb",
            )
            for i in range(1, 31)
        )

    async def get_health(self, pod: int, node: int):
        self.calls.append("health")
        return aci_facts.AciHealth(score=100)


def _source(devices: list[AciDevice], source_id: str = "fab", **kw: Any) -> AciSource:
    return AciSource(source_id, FakeDevices(devices, **kw), FakeDetails(), None, None, None)  # type: ignore[arg-type]


class FakeReaderAci:
    def __init__(self, sources: tuple[AciSource, ...] = (), error: Exception | None = None) -> None:
        self._sources, self.error, self.calls = sources, error, 0

    async def sources(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self._sources


def _box(reader: Any, sharing: SharingPolicy = ALL) -> Toolbox:
    redactor = Redactor()
    redactor.add_known_secrets((SECRET,))
    ctx = ToolContext(
        user_id=1, redactor=redactor, extras={ACI_READER_KEY: reader}, sharing=sharing
    )
    return Toolbox(build_aci_tools(), ctx)


def _call(box: Toolbox, tool: str, /, **tool_input: Any) -> ToolOutput:
    return asyncio.run(box.execute(ToolCall(id="1", name=tool, input=tool_input)))


def _json(out: ToolOutput) -> dict[str, Any]:
    assert not out.is_error, out.content
    return json.loads(out.content)


def _reader(*devices: AciDevice) -> FakeReaderAci:
    return FakeReaderAci((_source(list(devices)),))


# -- find / list -------------------------------------------------------------------------------


def test_find_by_name_is_case_insensitive_with_wildcards() -> None:
    box = _box(_reader(LEAF1, LEAF2, SPINE))
    assert [
        m["node_id"] for m in _json(_call(box, "find_aci_device", name="LEAF-1*"))["matches"]
    ] == [101, 102]


def test_find_keys_are_alternatives_first_hit_wins() -> None:
    box = _box(_reader(LEAF1, LEAF2))
    out = _json(_call(box, "find_aci_device", node_id=102, name="leaf-101"))
    assert [m["node_id"] for m in out["matches"]] == [102]
    out = _json(_call(box, "find_aci_device", node_id=999, name="leaf-101"))
    assert [m["node_id"] for m in out["matches"]] == [101]


def test_find_hides_raw_and_dn_and_reports_misses() -> None:
    box = _box(_reader(LEAF1))
    match = _json(_call(box, "find_aci_device", serial_number="sn101"))["matches"][0]
    assert "raw" not in match and "dn" not in match and match["serial_number"] == "SN101"
    out = _json(_call(box, "find_aci_device", name="nope"))
    assert out["matches"] == [] and "no leaf or spine" in out["message"].lower()


def test_find_needs_one_key() -> None:
    assert _call(_box(_reader(LEAF1)), "find_aci_device").is_error


def test_list_filters_and_pages() -> None:
    box = _box(_reader(LEAF1, LEAF2, SPINE))
    out = _json(_call(box, "list_aci_devices", role="leaf", limit=1))
    assert out["total"] == 2 and out["has_more"] and len(out["devices"]) == 1
    out = _json(_call(box, "list_aci_devices", name_contains="SPINE"))
    assert [d["node_id"] for d in out["devices"]] == [201]


def test_several_sources_and_one_failing_source() -> None:
    good = _source([LEAF1], "a")
    bad = _source([], "b", error=AciAuthError(f"401 {SECRET}"))
    out = _json(_call(_box(FakeReaderAci((good, bad))), "list_aci_devices"))
    assert out["devices"][0]["source_id"] == "a"
    assert out["source_errors"] == [
        {"source_id": "b", "error": aci_tools._failure_sentence(AciAuthError())}
    ]
    assert SECRET not in json.dumps(out)


def test_all_sources_failing_is_an_error_without_upstream_text() -> None:
    bad = _source([], "b", error=AciAPIError(f"500 {SECRET}"))
    out = _call(_box(FakeReaderAci((bad,))), "list_aci_devices")
    assert out.is_error and SECRET not in out.content


def test_source_argument_narrows() -> None:
    reader = FakeReaderAci((_source([LEAF1], "a"), _source([LEAF2], "b")))
    out = _json(_call(_box(reader), "list_aci_devices", source="b"))
    assert [d["node_id"] for d in out["devices"]] == [102]
    assert _call(_box(reader), "list_aci_devices", source="zz").is_error


# -- gates -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool,args",
    [
        ("find_aci_device", {"name": "x"}),
        ("list_aci_devices", {}),
        ("get_aci_device_details", {"name": "x"}),
    ],
)
def test_no_inventory_switch_sends_nothing(tool: str, args: dict[str, Any]) -> None:
    reader = _reader(LEAF1)
    out = _call(_box(reader, NOTHING), tool, **args)
    assert "not_shared" in out.content and reader.calls == 0


@pytest.mark.parametrize("key", ["serial_number", "management_ip"])
def test_lookup_by_address_needs_the_addresses_switch(key: str) -> None:
    reader = _reader(LEAF1)
    out = _call(_box(reader, INVENTORY_ONLY), "find_aci_device", **{key: "x"})
    assert "not_shared" in out.content and reader.calls == 0


def test_without_addresses_the_fields_are_withheld_and_named() -> None:
    out = _json(_call(_box(_reader(LEAF1), INVENTORY_ONLY), "list_aci_devices"))
    row = out["devices"][0]
    assert not {"serial_number", "management_ip", "tep_address"} & set(row)
    assert {"serial_number", "management_ip", "tep_address"} <= set(out["withheld_fields"])


# -- reader errors -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error,needle",
    [
        (AciNotConfiguredError(), "add one"),
        (AciSourcesUnusableError(), "none is usable"),
        (AciAccessError(), "lacks the permission"),
    ],
)
def test_reader_errors_are_fixed_sentences(error: Exception, needle: str) -> None:
    out = _call(_box(FakeReaderAci(error=error)), "list_aci_devices")
    assert out.is_error and needle in out.content


# -- details -----------------------------------------------------------------------------------


def test_details_default_facts_and_field_rules() -> None:
    box = _box(_reader(LEAF1))
    out = _json(_call(box, "get_aci_device_details", node_id=101))
    assert list(out["facts"]) == ["device", "software"]
    assert out["facts"]["device"]["data"]["serial_number"] == "SN101"
    assert "dn" not in json.dumps(out)
    inv = _json(_call(_box(_reader(LEAF1), INVENTORY_ONLY), "get_aci_device_details", node_id=101))
    assert "serial_number" not in inv["facts"]["device"]["data"]


def test_details_one_failing_fact_keeps_the_others_and_redacts() -> None:
    src = AciSource("fab", FakeDevices([LEAF1]), FakeDetails(fail={"interfaces"}), None, None, None)  # type: ignore[arg-type]
    out = _json(
        _call(
            _box(FakeReaderAci((src,))),
            "get_aci_device_details",
            node_id=101,
            facts=["interfaces", "health"],
        )
    )
    assert "error" in out["facts"]["interfaces"] and out["facts"]["health"]["data"]["score"] == 100
    assert SECRET not in json.dumps(out)


def test_details_pages_and_filters_interfaces_and_gates_descriptions() -> None:
    box = _box(_reader(LEAF1))
    out = _json(
        _call(
            box,
            "get_aci_device_details",
            node_id=101,
            facts=["interfaces"],
            interface_name_contains="eth1/2",
            limit=5,
        )
    )
    data = out["facts"]["interfaces"]["data"]
    assert data["total"] == 11 and len(data["items"]) == 5 and data["has_more"]
    assert SECRET not in json.dumps(out)  # redacted description
    no_content = _json(
        _call(
            _box(_reader(LEAF1), SharingPolicy(inventory=True, addresses=True)),
            "get_aci_device_details",
            node_id=101,
            facts=["interfaces"],
        )
    )
    assert "description" not in no_content["facts"]["interfaces"]["data"]["items"][0]
    assert "description" in no_content["withheld_fields"]


def test_details_ambiguous_and_missing() -> None:
    box = _box(_reader(LEAF1, LEAF2))
    out = _call(box, "get_aci_device_details", name="leaf-*")
    assert out.is_error and "leaf-101" in out.content and "leaf-102" in out.content
    assert _json(_call(box, "get_aci_device_details", name="x"))["found"] is False


def test_facts_match_the_step() -> None:
    assert set(aci_tools.Fact.__args__) == set(FACTS)  # type: ignore[attr-defined]
    assert set(aci_tools._FACT_METHODS) == set(FACTS) - {"device", "software"}


def _model_fields() -> set[str]:
    names: set[str] = set()
    for cls in vars(aci_facts).values():
        if (
            isinstance(cls, type)
            and issubclass(cls, aci_facts._Fact)
            and cls is not aci_facts._Fact
        ):
            names |= set(cls.model_fields)
    return names | set(AciDevice.model_fields)


def test_every_model_field_has_a_rule_or_is_deliberately_excluded() -> None:
    unruled = {f for f in _model_fields() if f not in aci_fields.RULES}
    assert unruled <= aci_fields.EXCLUDED, unruled


# -- wiring ------------------------------------------------------------------------------------


def _session(**overrides: Any):
    base: dict[str, Any] = {
        "user_id": 7,
        "reader": FakeReader(),
        "store": ResultStore(InMemoryResultBackend()),
        "sharing": ALL,
        "may_query_batfish": True,
        "aci_reader": _reader(LEAF1),
    }
    base.update(overrides)
    return build_general_session(**base)


def test_the_surface_offers_the_aci_tools_and_the_prompt() -> None:
    session = _session()
    names = {s.name for s in session.toolbox.specs()}
    assert {"find_aci_device", "list_aci_devices", "get_aci_device_details"} <= names
    assert "Cisco ACI" in session.system


def test_the_surface_without_a_reader_has_no_aci_tools() -> None:
    session = _session(aci_reader=None)
    assert not {s.name for s in session.toolbox.specs()} & {"find_aci_device", "list_aci_devices"}


def test_playbooks_may_name_the_tools_and_none_writes() -> None:
    assert {
        "find_aci_device",
        "list_aci_devices",
        "get_aci_device_details",
    } <= known_general_tool_names()
    assert all(
        t.name.split("_")[0] in {"find", "list", "get", "search", "check"}
        for t in build_aci_tools()
    )


# -- review findings ---------------------------------------------------------------------------


class _ContractsDetails(FakeDetails):
    async def get_contracts(self, pod: int, node: int):
        rules = tuple(
            aci_facts.AciContractRule(filter_id=f"f{i}", action="permit") for i in range(40)
        )
        filters = tuple(
            aci_facts.AciFilterEntry(filter_id=f"f{i}", protocol="tcp") for i in range(5)
        )
        return aci_facts.AciContracts(rules=rules, filters=filters)


def test_contract_rules_and_filters_page_independently() -> None:
    src = AciSource("fab", FakeDevices([LEAF1]), _ContractsDetails(), None, None, None)  # type: ignore[arg-type]
    box = _box(FakeReaderAci((src,)))
    first = _json(
        _call(box, "get_aci_device_details", node_id=101, facts=["contracts"], limit=25, offset=25)
    )["facts"]["contracts"]["data"]
    assert first["rules"]["offset"] == 25 and len(first["rules"]["items"]) == 15
    assert first["filters"]["offset"] == 0 and len(first["filters"]["items"]) == 5
    second = _json(
        _call(box, "get_aci_device_details", node_id=101, facts=["contracts"], filter_offset=3)
    )["facts"]["contracts"]["data"]
    assert second["rules"]["offset"] == 0 and len(second["filters"]["items"]) == 2


def test_a_switch_without_a_pod_id_is_not_read_as_pod_one() -> None:
    nopod = LEAF1.model_copy(update={"pod_id": None})
    details = FakeDetails()
    src = AciSource("fab", FakeDevices([nopod]), details, None, None, None)  # type: ignore[arg-type]
    out = _call(_box(FakeReaderAci((src,))), "get_aci_device_details", node_id=101)
    assert out.is_error and "pod id" in out.content and details.calls == []


def test_the_ambiguity_error_is_redacted() -> None:
    tricky = _device(301, f"leaf-{SECRET}")
    other = _device(302, f"leaf-{SECRET}-b")
    out = _call(_box(_reader(tricky, other)), "get_aci_device_details", name="leaf-*")
    assert out.is_error and SECRET not in out.content


def test_an_external_epg_keeps_a_readable_identity_without_the_dn() -> None:
    class ExtDetails(FakeDetails):
        async def get_epgs(self, pod: int, node: int):
            return (
                aci_facts.AciEpg(
                    name="Heroes:ext",
                    epg_dn="uni/tn-Heroes/out-corp/instP-default",
                    tenant="Heroes",
                ),
                aci_facts.AciEpg(
                    epg_dn="uni/tn-Heroes/ap-Save/epg-web",
                    tenant="Heroes",
                    app_profile="Save",
                    epg="web",
                ),
            )

    src = AciSource("fab", FakeDevices([LEAF1]), ExtDetails(), None, None, None)  # type: ignore[arg-type]
    out = _call(_box(FakeReaderAci((src,))), "get_aci_device_details", node_id=101, facts=["epgs"])
    items = _json(out)["facts"]["epgs"]["data"]["items"]
    assert [i["epg_path"] for i in items] == [
        "Heroes/corp/default (external)",
        "Heroes/Save/web",
    ]
    assert "uni/tn-" not in out.content and "epg_dn" not in out.content


class _AllFactsDetails(FakeDetails):
    async def get_hardware(self, pod: int, node: int):
        return ()

    get_neighbors = get_vlans = get_routes = get_hardware

    async def get_faults(self, pod: int, node: int):
        return aci_facts.AciFaults()


def test_asking_for_many_facts_costs_more_of_the_budget() -> None:
    src = AciSource("fab", FakeDevices([LEAF1]), _AllFactsDetails(), None, None, None)  # type: ignore[arg-type]
    box = _box(FakeReaderAci((src,)))
    nine = [
        "device",
        "software",
        "hardware",
        "interfaces",
        "neighbors",
        "vlans",
        "health",
        "faults",
        "routes",
    ]
    # 9 facts = 1 + 8 // 4 = 3 slots, so six calls use 18 of 20 and the seventh does not fit.
    for _ in range(6):
        assert not _call(box, "get_aci_device_details", node_id=101, facts=nine).is_error
    assert _call(box, "get_aci_device_details", node_id=101, facts=nine).is_error
