"""Neighbour discovery tools (doc/AI_TOOL_CHAIN.md §24): proposal, result, model, sources."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from nautobot_read.queries import dcim

from core.config import settings
from services.ai_assistant import device_token
from services.ai_assistant.data_sharing import DataClass, SharingPolicy
from services.ai_assistant.device_access import (
    DeviceAccessDeniedError,
    DeviceAmbiguousError,
    DeviceNoAddressError,
    DeviceNotFoundError,
    ResolvedDevice,
)
from services.ai_assistant.device_exec_service import _shape_blocks
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.results.store import InMemoryResultBackend, ResultStore, StoredResult
from services.ai_assistant.tools import neighbor_tools as nt
from services.ai_assistant.tools.base import ToolContext, ToolOutput
from services.ai_assistant.tools.batfish_tools import BATFISH_READER_KEY, BatfishAnswer
from services.ai_assistant.tools.device_tools import DEVICE_RESOLVER_KEY
from services.ai_assistant.tools.nautobot_tools import NAUTOBOT_READER_KEY
from services.ai_assistant.tools.result_tools import RESULT_STORE_KEY

USER = 7
IOS = ResolvedDevice("nb1", "dev-1", "LAB", "10.1.2.3", "cisco_ios", "cisco_ios")
COMWARE = ResolvedDevice("nb1", "dev-2", "HP1", "10.1.2.4", "hp_comware", "hp_comware")

CDP = """-------------------------
Device ID: sw2.example.com(FOC1234)
Entry address(es):
  IP address: 192.0.2.2
Platform: cisco WS-C3850-24P,  Capabilities: Switch IGMP
Interface: GigabitEthernet1/0/1,  Port ID (outgoing port): GigabitEthernet0/24
Holdtime : 150 sec

Version :
Cisco IOS Software, IOS-XE Software

advertisement version: 2
Management address(es):
  IP address: 192.0.2.2

-------------------------
Device ID: ghost
Entry address(es):
  IP address: 10.9.9.2
Platform: cisco ISR4331/K9,  Capabilities: Router
Interface: GigabitEthernet1/0/2,  Port ID (outgoing port): GigabitEthernet0/0/1
Holdtime : 130 sec

Version :
Cisco IOS XE

advertisement version: 2
Management address(es):
  IP address: 10.9.9.2

Total cdp entries displayed : 2
"""
OSPF = """Neighbor ID     Pri   State           Dead Time   Address         Interface
10.0.0.1          1   FULL/DR         00:00:35    192.0.2.1       GigabitEthernet1/0/3
"""
PROTOCOLS = 'Routing Protocol is "ospf 1"\n  Router ID 10.0.0.5\n'


@pytest.fixture(autouse=True)
def _secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "secret_key", "k" * 40)


class FakeResolver:
    def __init__(
        self, device: ResolvedDevice = IOS, known: dict[str, Exception | None] | None = None
    ):
        self.device, self.known, self.names = device, known or {}, []

    async def resolve(self, name: str) -> ResolvedDevice:
        self.names.append(name)
        if name in self.known:
            if self.known[name] is not None:
                raise self.known[name]  # type: ignore[misc]
            return ResolvedDevice("nb1", f"id-{name}", name.upper(), "10.0.0.1", None, None)
        if self.known:
            raise DeviceNotFoundError
        return self.device


def _ctx(resolver: Any = None, **extras: Any) -> ToolContext:
    return ToolContext(
        user_id=USER,
        redactor=Redactor(),
        extras={DEVICE_RESOLVER_KEY: resolver or FakeResolver(), **extras},
        sharing=SharingPolicy(inventory=True, addresses=True, content=True),
    )


def _tool(name: str):
    return next(t for t in nt.build_neighbor_tools() if t.name == name)


def _call(name: str, ctx: ToolContext, **args: Any) -> ToolOutput:
    tool = _tool(name)
    return asyncio.run(tool.handler(ctx, tool.input_model(**args)))


# -- propose_neighbor_discovery ----------------------------------------------------------------


def test_l2_discovery_is_a_signed_device_command_proposal() -> None:
    out = _call("propose_neighbor_discovery", _ctx(), device="LAB")

    assert not out.is_error and out.proposal is not None
    assert out.proposal["kind"] == "device_command"
    assert out.proposal["commands"] == ["show cdp neighbors detail", "show lldp neighbors detail"]
    assert out.proposal["parser"] == "textfsm"
    grant = device_token.verify_token(out.proposal["token"], user_id=USER)
    assert grant.commands == ("show cdp neighbors detail", "show lldp neighbors detail")
    assert grant.parser == "textfsm"
    assert "RAW" in out.content


def test_protocol_discovery_is_raw_text_and_tells_the_model_to_ask() -> None:
    out = _call("propose_neighbor_discovery", _ctx(), device="LAB", layer="l3", protocol="discover")

    assert out.proposal is not None
    assert out.proposal["parser"] == "none"
    assert "show ip protocols" in out.proposal["commands"]
    assert "ask the user" in out.content


def test_a_vrf_command_comes_from_the_catalogue() -> None:
    out = _call(
        "propose_neighbor_discovery",
        _ctx(),
        device="LAB",
        layer="l3",
        protocol="routing_table",
        vrf="BLUE",
    )

    assert out.proposal is not None
    assert out.proposal["commands"] == ["show ip route vrf BLUE"]


@pytest.mark.parametrize(
    ("args", "fragment"),
    [
        ({"layer": "l3", "protocol": "ospf", "vrf": "BLUE"}, "not supported for a VRF"),
        ({"layer": "l3", "protocol": "eigrp", "vrf": "x;reload"}, "String should match"),
    ],
)
def test_impossible_requests_are_refused_before_a_card_exists(args, fragment) -> None:
    tool = _tool("propose_neighbor_discovery")
    try:
        model = tool.input_model(device="LAB", **args)
    except ValueError as exc:  # the schema refuses a bad VRF name outright
        assert fragment in str(exc)
        return

    out = asyncio.run(tool.handler(_ctx(), model))

    assert out.is_error and out.proposal is None
    assert fragment in out.content


def test_an_unsupported_platform_gets_no_proposal() -> None:
    out = _call("propose_neighbor_discovery", _ctx(FakeResolver(COMWARE)), device="HP1")

    assert out.is_error and out.proposal is None
    assert "propose_device_command" in out.content


def test_a_device_problem_is_reported_as_is() -> None:
    out = _call(
        "propose_neighbor_discovery",
        _ctx(FakeResolver(known={"LAB": DeviceAmbiguousError()})),
        device="LAB",
    )

    assert out.is_error and "More than one" in out.content


def test_the_model_cannot_pass_commands() -> None:
    fields = _tool("propose_neighbor_discovery").input_model.model_fields

    assert set(fields) == {"device", "layer", "protocol", "vrf"}
    with pytest.raises(ValueError):
        _tool("propose_neighbor_discovery").input_model(device="LAB", commands=["show version"])


# -- get_discovery_result ----------------------------------------------------------------------


def _store_run(store: ResultStore, outputs: list[tuple[str, str]], **meta: Any) -> str:
    text, _, spans = _shape_blocks(outputs, lambda value: value)
    full = {
        "commands": [c for c, _ in outputs],
        "spans": spans,
        "parser": "textfsm",
        "network_driver": "cisco_ios",
        "platform": "cisco_ios",
        "device_name": "LAB",
        **meta,
    }
    return asyncio.run(
        store.put(USER, StoredResult("device_command", DataClass.CONTENT, text=text, meta=full))
    )


@pytest.fixture
def store() -> ResultStore:
    return ResultStore(InMemoryResultBackend())


def test_cdp_output_becomes_neighbor_records_matched_to_the_inventory(store) -> None:
    handle = _store_run(
        store, [("show cdp neighbors detail", CDP), ("show lldp neighbors detail", "")]
    )
    resolver = FakeResolver(known={"sw2": None})

    out = _call("get_discovery_result", _ctx(resolver, **{RESULT_STORE_KEY: store}), handle=handle)

    assert not out.is_error
    payload = json.loads(out.content)
    by_name = {r["neighbor_name"]: r for r in payload["rows"]}
    assert by_name["sw2.example.com(FOC1234)"]["inventory"]["matched"] is True
    assert by_name["sw2.example.com(FOC1234)"]["inventory"]["device"] == "SW2"
    # only "sw2" is in the inventory, so the match is on the host part and says so
    assert by_name["sw2.example.com(FOC1234)"]["inventory"]["how"] == "short_name"
    assert by_name["sw2.example.com(FOC1234)"]["neighbor_ip"] == "192.0.2.2"
    assert by_name["ghost"]["inventory"] == {"matched": False}
    assert payload["summary"]["l2"] == 2 and payload["summary"]["not_in_inventory"] == 1
    assert payload["source"] == "live"
    # the empty LLDP table is not a parse error that hides the CDP result
    assert [e["command"] for e in payload["errors"]] == ["show lldp neighbors detail"]


def test_l3_adjacency_records_carry_the_vrf(store) -> None:
    handle = _store_run(store, [("show ip ospf neighbor", OSPF)])

    out = _call("get_discovery_result", _ctx(**{RESULT_STORE_KEY: store}), handle=handle)

    [row] = json.loads(out.content)["rows"]
    assert (row["protocol"], row["vrf"], row["neighbor_ip"], row["state"]) == (
        "ospf",
        "default",
        "192.0.2.1",
        "FULL/DR",
    )


def test_a_command_that_is_not_a_neighbour_command_is_not_read_as_one(store) -> None:
    handle = _store_run(store, [("show version", "Cisco IOS Software")])

    out = _call("get_discovery_result", _ctx(**{RESULT_STORE_KEY: store}), handle=handle)

    assert out.is_error and "not the output of a neighbour discovery" in out.content


def test_protocol_discovery_output_is_not_parsed_as_neighbours(store) -> None:
    handle = _store_run(store, [("show ip protocols", PROTOCOLS)], parser="none")

    out = _call("get_discovery_result", _ctx(**{RESULT_STORE_KEY: store}), handle=handle)

    assert out.is_error and "fetch_slice" in out.content


def test_an_unknown_handle_and_the_content_opt_in_are_checked(store) -> None:
    ctx = _ctx(**{RESULT_STORE_KEY: store})
    assert _call("get_discovery_result", ctx, handle="res_000000000000").is_error

    handle = _store_run(store, [("show cdp neighbors detail", CDP)])
    closed = ToolContext(
        user_id=USER,
        redactor=Redactor(),
        extras={RESULT_STORE_KEY: store},
        sharing=SharingPolicy(content=False),
    )
    out = _call("get_discovery_result", closed, handle=handle)
    assert "not_shared" in out.content


class _NautobotReader:
    async def context(self) -> object:
        return object()


def _patch_interfaces(monkeypatch, pages: list[dict], seen: list | None = None) -> None:
    calls = iter(pages)

    async def fake_list_interfaces(ctx, **kwargs):
        if seen is not None:
            seen.append(kwargs)
        return next(calls)

    monkeypatch.setattr(dcim, "list_interfaces", fake_list_interfaces)


def _page(items, *, has_more=False):
    return {"items": items, "returned": len(items), "has_more": has_more}


def _cabled(port, device, interface):
    return {"name": port, "connected_to": {"device": device, "interface": interface}}


def test_the_comparison_with_nautobot_reports_each_class(store, monkeypatch) -> None:
    handle = _store_run(store, [("show cdp neighbors detail", CDP)])
    seen: list = []
    _patch_interfaces(
        monkeypatch,
        [_page([_cabled("Gi1/0/1", "SW2", "Gi0/24"), _cabled("Gi1/0/9", "sw7", "Gi0/2")])],
        seen,
    )
    ctx = _ctx(**{RESULT_STORE_KEY: store, NAUTOBOT_READER_KEY: _NautobotReader()})

    out = _call("get_discovery_result", ctx, handle=handle, compare_with_nautobot=True)

    comparison = json.loads(out.content)["comparison_with_nautobot"]
    assert comparison["counts"] == {
        "confirmed": 1,
        "conflict": 0,
        "undocumented": 1,
        "not_seen_live": 1,
    }
    assert comparison["complete"] is True
    # the device is the one the output came from, recorded when it was run
    assert comparison["device"] == "LAB" and seen[0]["device"] == "LAB"


def test_the_model_cannot_name_the_device_to_compare_with() -> None:
    fields = _tool("get_discovery_result").input_model.model_fields

    assert set(fields) == {"handle", "compare_with_nautobot"}


def test_an_output_stored_without_its_device_is_not_compared(store, monkeypatch) -> None:
    text, _, spans = _shape_blocks([("show cdp neighbors detail", CDP)], lambda v: v)
    old_meta = {
        "commands": ["show cdp neighbors detail"],
        "spans": spans,
        "parser": "textfsm",
        "network_driver": "cisco_ios",
        "platform": "cisco_ios",
    }
    handle = asyncio.run(
        store.put(USER, StoredResult("device_command", DataClass.CONTENT, text=text, meta=old_meta))
    )
    _patch_interfaces(monkeypatch, [])
    ctx = _ctx(**{RESULT_STORE_KEY: store, NAUTOBOT_READER_KEY: _NautobotReader()})

    out = _call("get_discovery_result", ctx, handle=handle, compare_with_nautobot=True)

    assert (
        "run the discovery again"
        in json.loads(out.content)["comparison_with_nautobot"]["unavailable"]
    )


def test_all_pages_of_cabled_interfaces_are_read(store, monkeypatch) -> None:
    handle = _store_run(store, [("show cdp neighbors detail", CDP)])
    seen: list = []
    _patch_interfaces(
        monkeypatch,
        [
            _page([_cabled("Gi1/0/9", "sw7", "Gi0/2")], has_more=True),
            _page([_cabled("Gi1/0/1", "SW2", "Gi0/24")]),
        ],
        seen,
    )
    ctx = _ctx(**{RESULT_STORE_KEY: store, NAUTOBOT_READER_KEY: _NautobotReader()})

    out = _call("get_discovery_result", ctx, handle=handle, compare_with_nautobot=True)

    comparison = json.loads(out.content)["comparison_with_nautobot"]
    assert [call["offset"] for call in seen] == [0, 1]
    assert comparison["complete"] is True
    assert comparison["counts"]["confirmed"] == 1  # the cable on the second page counts


def test_a_device_with_too_many_cables_is_compared_incompletely_and_says_so(
    store, monkeypatch
) -> None:
    handle = _store_run(store, [("show cdp neighbors detail", CDP)])
    monkeypatch.setattr(nt, "MAX_DOCUMENTED_INTERFACES", 2)
    monkeypatch.setattr(nt, "DOCUMENTED_PAGE", 1)
    _patch_interfaces(
        monkeypatch,
        [
            _page([_cabled("Gi1/0/9", "sw7", "Gi0/2")], has_more=True),
            _page([_cabled("Gi1/0/8", "sw6", "Gi0/2")], has_more=True),
        ],
    )
    ctx = _ctx(**{RESULT_STORE_KEY: store, NAUTOBOT_READER_KEY: _NautobotReader()})

    out = _call("get_discovery_result", ctx, handle=handle, compare_with_nautobot=True)

    comparison = json.loads(out.content)["comparison_with_nautobot"]
    assert comparison["complete"] is False
    assert "undocumented" not in comparison and "not_seen_live" not in comparison
    assert comparison["counts"]["not_compared"] == 2  # both live ports: not claimed missing
    assert "Say so" in comparison["note"]


def test_the_comparison_says_why_it_is_unavailable(store) -> None:
    handle = _store_run(store, [("show cdp neighbors detail", CDP)])

    out = _call(
        "get_discovery_result",
        _ctx(**{RESULT_STORE_KEY: store}),
        handle=handle,
        compare_with_nautobot=True,
    )

    unavailable = json.loads(out.content)["comparison_with_nautobot"]["unavailable"]
    assert "no Nautobot source" in unavailable


# -- review findings: inventory lookups and rows that vanish ---------------------------------------


def test_an_ambiguous_or_denied_lookup_is_never_a_match(store) -> None:
    handle = _store_run(store, [("show cdp neighbors detail", CDP)])
    resolver = FakeResolver(
        known={"sw2.example.com": DeviceAmbiguousError(), "ghost": DeviceAccessDeniedError()}
    )

    out = _call("get_discovery_result", _ctx(resolver, **{RESULT_STORE_KEY: store}), handle=handle)

    payload = json.loads(out.content)
    verdicts = {r["neighbor_name"]: r["inventory"] for r in payload["rows"]}
    assert verdicts["sw2.example.com(FOC1234)"]["matched"] is None
    assert "more than one" in verdicts["sw2.example.com(FOC1234)"]["note"]
    assert verdicts["ghost"]["matched"] is None
    assert payload["summary"]["inventory_unclear"] == 2
    assert payload["summary"]["not_in_inventory"] == 0


def test_a_device_without_an_address_is_still_found_by_name(store) -> None:
    class NoAddress(FakeResolver):
        async def resolve(self, name):
            raise DeviceNoAddressError

    handle = _store_run(store, [("show cdp neighbors detail", CDP)])

    out = _call(
        "get_discovery_result", _ctx(NoAddress(), **{RESULT_STORE_KEY: store}), handle=handle
    )

    first = json.loads(out.content)["rows"][0]
    assert first["inventory"]["matched"] is True


def test_rows_that_are_all_dropped_are_an_error_not_an_empty_list(store, monkeypatch) -> None:
    """Rows came back but none was usable (say, all of another VRF): not 'no neighbours'."""
    handle = _store_run(store, [("show ip ospf neighbor", OSPF)])
    ctx = _ctx(**{RESULT_STORE_KEY: store})
    assert len(json.loads(_call("get_discovery_result", ctx, handle=handle).content)["rows"]) == 1

    monkeypatch.setattr(nt, "normalize_rows", lambda step, rows: [])
    payload = json.loads(_call("get_discovery_result", ctx, handle=handle).content)

    assert payload["rows"] == []
    assert payload["errors"][0]["command"] == "show ip ospf neighbor"
    assert "none could be read as a neighbour" in payload["errors"][0]["error"]


# -- get_modelled_neighbors / get_neighbor_sources -----------------------------------------------


class FakeBatfish:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows, self.calls = rows, []

    async def list_sources(self) -> list[str]:
        return ["lab"]

    async def query(self, kind, source_id, network, snapshot, params):
        self.calls.append((kind, params))
        return BatfishAnswer(
            rows=self.rows,
            snapshot="run-2",
            snapshot_created="2026-11-01T10:00:00Z",
            nodes_resolved={"LAB": "lab"},
        )


def test_modelled_neighbors_are_l3_only_and_labelled() -> None:
    reader = FakeBatfish(
        [
            {
                "Interface": "lab[Gi0/0]",
                "IPs": ["10.0.0.1"],
                "Remote_Interface": "r2[Gi0/1]",
                "Remote_IPs": ["10.0.0.2"],
            }
        ]
    )
    ctx = _ctx(
        **{BATFISH_READER_KEY: reader, RESULT_STORE_KEY: ResultStore(InMemoryResultBackend())}
    )

    out = _call("get_modelled_neighbors", ctx, network="net1", device="LAB", edge_type="ospf")

    payload = json.loads(out.content)
    assert reader.calls == [("edges", {"nodes": "LAB", "edge_type": "ospf"})]
    assert payload["rows"][0]["neighbor_name"] == "r2"
    assert payload["source"] == "model" and payload["snapshot"] == "run-2"
    assert "no CDP/LLDP" in payload["note"]


def test_sources_lists_the_evidence_and_the_platform_support() -> None:
    out = _call("get_neighbor_sources", _ctx(**{NAUTOBOT_READER_KEY: object()}), device="LAB")

    payload = json.loads(out.content)
    assert payload["live"]["platform_family"] == "ios"
    assert "ospf" in payload["live"]["supported"]["l3"]
    assert payload["documented"]["use"] == "cabled_only=true"
    assert any("no data" in rule for rule in payload["rules"])


def test_sources_without_a_device_resolver_say_live_is_off() -> None:
    ctx = ToolContext(
        user_id=USER, redactor=Redactor(), extras={}, sharing=SharingPolicy(inventory=True)
    )

    out = _call("get_neighbor_sources", ctx)

    assert json.loads(out.content)["live"]["available"] is False


def test_a_catalogue_command_that_breaks_the_policy_never_reaches_a_card(monkeypatch) -> None:
    """The proposal checks the plan against the command policy again (defence in depth)."""
    bad = nt.catalogue.DiscoveryPlan(
        (nt.catalogue.Step("reload", "l2", "cdp", "default"),), "textfsm"
    )
    monkeypatch.setattr(nt.catalogue, "plan_discovery", lambda *args: bad)

    out = _call("propose_neighbor_discovery", _ctx(), device="LAB")

    assert out.is_error and out.proposal is None
    assert "only full 'show' commands" in out.content
