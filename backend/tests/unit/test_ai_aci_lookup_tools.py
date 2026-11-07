"""ACI endpoint and subnet tools for Ask the Net: gates, filters, errors, wiring."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from models.aci_endpoint import AciEndpoint, AciEndpointAttachment
from models.aci_subnets import AciSubnet
from services.aci.common.exceptions import AciAPIError, AciAuthError, AciValidationError
from services.aci.endpoint_service import normalize_mac
from services.ai_assistant.aci_reader import AciSource
from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.providers.base import ToolCall
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.tools import aci_fields, aci_tools
from services.ai_assistant.tools.aci_tools import ACI_READER_KEY, build_aci_tools
from services.ai_assistant.tools.base import Toolbox, ToolContext, ToolOutput
from services.ai_assistant.tools.playbook_tools import known_general_tool_names

ALL = SharingPolicy(inventory=True, addresses=True, content=True)
INVENTORY_ONLY = SharingPolicy(inventory=True)
ADDRESSES_ONLY = SharingPolicy(addresses=True)
SECRET = "hunter2hunter2"

EP = AciEndpoint(
    mac="45:CD:BB:C0:00:00",
    ips=("10.193.101.4", "10.193.102.3"),
    tenant="SnV",
    app_profile="Chaos",
    epg="Web",
    encap="vlan-125",
    attachments=(AciEndpointAttachment(pod_id=1, node_ids=(101, 102), interface="SnV_FI-1A"),),
)


def _subnet(prefix: str, tenant: str, bd: str, vrf: str = "vrf1") -> AciSubnet:
    return AciSubnet(
        prefix=prefix,
        gateway=prefix.split("/")[0][:-1] + "1",
        tenant=tenant,
        bridge_domain=bd,
        vrf=vrf,
        scope=("private",),
    )


SUBNETS = (
    _subnet("10.1.120.0/22", "Heroes", "Hero_Land", "Heroes_Only"),
    _subnet("10.20.86.0/24", "INET_TN", "INET_BD", "INET_VRF"),
    _subnet("10.20.0.0/24", "prod", "Booking-BD"),
    _subnet("2001:db8::/64", "prod", "v6-BD"),
)


class FakeEndpoints:
    def __init__(self, found: tuple[AciEndpoint, ...] = (EP,), error: Exception | None = None):
        self.found, self.error, self.calls = found, error, []

    async def find(self, address: str):
        self.calls.append(address)
        if self.error is not None:
            raise self.error
        if normalize_mac(address) is None and address.count(".") != 3:
            raise AciValidationError("Not an IPv4 or MAC address")
        return self.found


class FakeListing(FakeEndpoints):
    """FakeEndpoints that can also list and trace history."""

    def __init__(self, listed=(EP,), history=(), error: Exception | None = None) -> None:
        super().__init__()
        self.listed, self.histories, self.error = tuple(listed), tuple(history), error
        self.list_calls: list[dict[str, Any]] = []

    async def list_endpoints(self, **kwargs):
        self.list_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.listed

    async def history(self, address: str):
        if self.error is not None:
            raise self.error
        if normalize_mac(address) is None and address.count(".") != 3:
            raise AciValidationError("Not an IPv4 or MAC address")
        return self.histories


class FakeSubnets:
    def __init__(self, subnets: tuple[AciSubnet, ...] = SUBNETS, error: Exception | None = None):
        self.subnets, self.error, self.calls = subnets, error, 0

    async def list_subnets(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.subnets


class Reader:
    def __init__(self, *sources: AciSource) -> None:
        self._sources, self.calls = sources, 0

    async def sources(self):
        self.calls += 1
        return self._sources


def _source(sid: str = "fab", endpoints: Any = None, subnets: Any = None) -> AciSource:
    return AciSource(sid, None, None, endpoints or FakeEndpoints(), subnets or FakeSubnets(), None)  # type: ignore[arg-type]


def _box(reader: Reader, sharing: SharingPolicy = ALL) -> Toolbox:
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


# -- find_aci_endpoint -------------------------------------------------------------------------


def test_endpoint_answer_has_location_and_source() -> None:
    out = _json(_call(_box(Reader(_source())), "find_aci_endpoint", address="10.193.101.4"))
    row = out["endpoints"][0]
    assert row["source_id"] == "fab" and row["epg"] == "Web" and row["tenant"] == "SnV"
    assert row["attachments"] == [{"pod_id": 1, "node_ids": [101, 102], "interface": "SnV_FI-1A"}]
    assert row["ips"] == ["10.193.101.4", "10.193.102.3"]


def test_unknown_endpoint_is_an_answer_with_the_caveat() -> None:
    reader = Reader(_source(endpoints=FakeEndpoints(())))
    out = _json(_call(_box(reader), "find_aci_endpoint", address="10.9.9.9"))
    assert out["endpoints"] == [] and "not learned" in out["message"]


def test_malformed_address_is_a_readable_error() -> None:
    out = _call(_box(Reader(_source())), "find_aci_endpoint", address="not-an-address")
    assert out.is_error and "IPv4 address or a MAC" in out.content


@pytest.mark.parametrize("sharing", [SharingPolicy(), INVENTORY_ONLY, ADDRESSES_ONLY])
@pytest.mark.parametrize(
    "tool,args",
    [("find_aci_endpoint", {"address": "10.1.1.1"}), ("list_aci_subnets", {})],
)
def test_both_switches_gate_the_whole_call_before_any_request(
    sharing: SharingPolicy, tool: str, args: dict[str, Any]
) -> None:
    reader = Reader(_source())
    out = _call(_box(reader, sharing), tool, **args)
    assert "not_shared" in out.content and reader.calls == 0


def test_endpoint_failing_source_is_a_fixed_sentence() -> None:
    good = _source("a")
    bad = _source("b", endpoints=FakeEndpoints(error=AciAuthError(f"401 {SECRET}")))
    out = _json(_call(_box(Reader(good, bad)), "find_aci_endpoint", address="10.193.101.4"))
    assert [e["source_id"] for e in out["endpoints"]] == ["a"]
    assert out["source_errors"][0]["source_id"] == "b" and SECRET not in json.dumps(out)


def test_endpoint_all_sources_failing_is_an_error_without_upstream_text() -> None:
    bad = _source(endpoints=FakeEndpoints(error=AciAPIError(f"500 {SECRET}")))
    out = _call(_box(Reader(bad)), "find_aci_endpoint", address="10.193.101.4")
    assert out.is_error and SECRET not in out.content


# -- list_aci_subnets --------------------------------------------------------------------------


def _prefixes(out: dict[str, Any]) -> list[str]:
    return [s["prefix"] for s in out["subnets"]]


def test_subnets_contains_ip() -> None:
    box = _box(Reader(_source()))
    assert _prefixes(_json(_call(box, "list_aci_subnets", contains_ip="10.1.121.7"))) == [
        "10.1.120.0/22"
    ]
    assert _prefixes(_json(_call(box, "list_aci_subnets", contains_ip="2001:db8::5"))) == [
        "2001:db8::/64"
    ]
    assert _json(_call(box, "list_aci_subnets", contains_ip="10.9.9.9"))["total"] == 0


def test_subnets_within_prefix_and_exact_prefix() -> None:
    box = _box(Reader(_source()))
    assert set(_prefixes(_json(_call(box, "list_aci_subnets", within="10.20.0.0/16")))) == {
        "10.20.86.0/24",
        "10.20.0.0/24",
    }
    assert _prefixes(_json(_call(box, "list_aci_subnets", prefix="10.20.86.0/24"))) == [
        "10.20.86.0/24"
    ]


def test_subnets_name_filters_and_paging() -> None:
    box = _box(Reader(_source()))
    assert _prefixes(
        _json(_call(box, "list_aci_subnets", tenant="prod", vrf="vrf1", bridge_domain="v6-BD"))
    ) == ["2001:db8::/64"]
    page = _json(_call(box, "list_aci_subnets", limit=2, offset=1))
    assert page["total"] == 4 and len(page["subnets"]) == 2 and page["has_more"]


@pytest.mark.parametrize(
    "args", [{"contains_ip": "999.1.1.1"}, {"within": "nonsense"}, {"prefix": "10.1.1.0/99"}]
)
def test_subnet_filters_are_validated_and_send_nothing(args: dict[str, Any]) -> None:
    reader = Reader(_source())
    assert _call(_box(reader), "list_aci_subnets", **args).is_error and reader.calls == 0


def test_subnet_failing_source_is_a_fixed_sentence() -> None:
    bad = _source("b", subnets=FakeSubnets(error=AciAuthError(f"401 {SECRET}")))
    out = _json(_call(_box(Reader(_source("a"), bad)), "list_aci_subnets"))
    assert out["source_errors"][0]["source_id"] == "b" and SECRET not in json.dumps(out)


def test_new_model_fields_all_have_a_rule() -> None:
    for model in (AciEndpoint, AciEndpointAttachment, AciSubnet):
        assert not set(model.model_fields) - set(aci_fields.RULES), model


def test_tools_are_registered_for_playbooks() -> None:
    assert {"find_aci_endpoint", "list_aci_subnets"} <= known_general_tool_names()


# -- rate limit --------------------------------------------------------------------------------


def test_reads_are_rate_limited_per_user_after_the_permission_check() -> None:
    reader = Reader(_source())
    box = _box(reader)
    outs = [
        _call(box, "find_aci_endpoint", address="10.193.101.4")
        for _ in range(aci_tools.RATE_ATTEMPTS + 1)
    ]
    assert not any(o.is_error for o in outs[:-1])
    assert outs[-1].is_error and "Too many ACI reads" in outs[-1].content
    assert reader.calls == aci_tools.RATE_ATTEMPTS + 1  # the permission is asked first


def test_a_denied_user_does_not_use_up_the_budget() -> None:
    from services.ai_assistant.aci_reader import AciAccessError

    class Denied(Reader):
        async def sources(self):
            raise AciAccessError

    box = _box(Denied())
    for _ in range(aci_tools.RATE_ATTEMPTS + 3):
        out = _call(box, "list_aci_subnets")
        assert "lacks the permission" in out.content


def test_a_full_subnet_read_costs_two_slots_of_the_budget() -> None:
    box = _box(Reader(_source()))
    ok = [_call(box, "list_aci_subnets") for _ in range(aci_tools.RATE_ATTEMPTS // 2)]
    assert not any(o.is_error for o in ok)
    assert _call(box, "list_aci_subnets").is_error  # 10 calls x 2 slots used the whole budget


def test_a_call_that_is_too_expensive_for_what_is_left_spends_nothing_more() -> None:
    reader = Reader(_source())
    box = _box(reader)
    for _ in range(aci_tools.RATE_ATTEMPTS - 1):
        assert not _call(box, "find_aci_endpoint", address="10.193.101.4").is_error
    assert _call(box, "list_aci_subnets").is_error  # needs 2, one is left
    assert not _call(box, "find_aci_endpoint", address="10.193.101.4").is_error  # the last slot


# -- list_aci_endpoints and get_aci_endpoint_history ------------------------------------------


def _other_endpoint(mac: str, ip: str, epg: str = "App") -> AciEndpoint:
    return AciEndpoint(
        mac=mac,
        ips=(ip,),
        tenant="SnV",
        app_profile="Chaos",
        epg=epg,
        vrf="SnV/v1",
        attachments=(AciEndpointAttachment(pod_id=1, node_ids=(101,), interface="eth1/3"),),
    )


def test_list_endpoints_rows_total_paging_and_the_within_filter() -> None:
    eps = [_other_endpoint(f"AA:BB:CC:00:00:0{i}", f"10.{i}.0.5") for i in range(1, 6)]
    reader = Reader(_source(endpoints=FakeListing(listed=eps)))
    box = _box(reader)
    out = _json(_call(box, "list_aci_endpoints", tenant="SnV", limit=2, offset=1))
    assert out["total"] == 5 and len(out["endpoints"]) == 2 and out["has_more"]
    assert out["endpoints"][0]["vrf"] == "SnV/v1" and out["endpoints"][0]["source_id"] == "fab"
    narrowed = _json(_call(box, "list_aci_endpoints", tenant="SnV", within="10.2.0.0/16"))
    assert [e["ips"] for e in narrowed["endpoints"]] == [["10.2.0.5"]]


def test_list_endpoints_passes_the_names_and_validates_the_input() -> None:
    listing = FakeListing()
    box = _box(Reader(_source(endpoints=listing)))
    _json(_call(box, "list_aci_endpoints", tenant="SnV", app_profile="Chaos", epg="Web"))
    assert listing.list_calls == [{"tenant": "SnV", "app_profile": "Chaos", "epg": "Web"}]
    assert _call(box, "list_aci_endpoints", tenant="SnV", epg="Web").is_error
    assert _call(box, "list_aci_endpoints", tenant="SnV", within="nonsense").is_error
    assert _call(box, "list_aci_endpoints").is_error


def test_an_empty_endpoint_listing_is_an_answer_and_too_many_is_a_fixed_sentence() -> None:
    empty = _json(
        _call(
            _box(Reader(_source(endpoints=FakeListing(listed=())))),
            "list_aci_endpoints",
            tenant="SnV",
            epg="Web",
            app_profile="Chaos",
        )
    )
    assert empty["endpoints"] == [] and "only once a host sends traffic" in empty["message"]
    big = AciAPIError(f"500 {SECRET}", code="too_many_objects")
    out = _call(
        _box(Reader(_source(endpoints=FakeListing(error=big)))), "list_aci_endpoints", tenant="T"
    )
    assert out.is_error and "narrow" in out.content and SECRET not in out.content


@pytest.mark.parametrize("sharing", [SharingPolicy(), INVENTORY_ONLY, ADDRESSES_ONLY])
@pytest.mark.parametrize(
    "tool,args",
    [
        ("list_aci_endpoints", {"tenant": "T"}),
        ("get_aci_endpoint_history", {"address": "10.1.1.1"}),
    ],
)
def test_the_endpoint_listing_and_history_need_both_switches_before_any_request(
    sharing: SharingPolicy, tool: str, args: dict[str, Any]
) -> None:
    reader = Reader(_source(endpoints=FakeListing()))
    out = _call(_box(reader, sharing), tool, **args)
    assert "not_shared" in out.content and reader.calls == 0


def _history(**kw):
    from models.aci_endpoint import (
        AciEndpointEvent,
        AciEndpointHistory,
        AciEndpointIpRecord,
        AciLeafEndpointRecord,
    )

    return AciEndpointHistory(
        mac="45:CD:BB:C0:00:00",
        tenant="SnV",
        app_profile="Chaos",
        epg="Web",
        last_changed="2026-11-07T12:00:00.000+00:00",
        ips=(
            AciEndpointIpRecord(address="10.193.101.4", learned_at="2026-11-06T08:00:00.000+00:00"),
        ),
        leaf_records=(
            AciLeafEndpointRecord(
                pod_id=1, node_id=101, interface="po1", first_seen="2026-11-05T10:00:00.000+00:00"
            ),
        ),
        events=(
            AciEndpointEvent(
                kind="fault",
                time="2026-11-07T11:00:00.000+00:00",
                code="F1",
                severity="major",
                description=f"duplicate address {SECRET}",
            ),
        ),
        **kw,
    )


def test_history_shows_timestamps_and_the_honest_note() -> None:
    reader = Reader(_source(endpoints=FakeListing(history=(_history(),))))
    out = _json(_call(_box(reader), "get_aci_endpoint_history", address="10.193.101.4"))
    row = out["endpoints"][0]
    assert row["last_changed"] == "2026-11-07T12:00:00.000+00:00"
    assert row["ips"][0]["learned_at"] == "2026-11-06T08:00:00.000+00:00"
    assert row["leaf_records"][0] == {
        "pod_id": 1,
        "node_id": 101,
        "interface": "po1",
        "first_seen": "2026-11-05T10:00:00.000+00:00",
    }
    assert "keeps no move history" in out["note"]
    assert SECRET not in json.dumps(out)  # the log text is redacted


def test_history_log_text_needs_the_content_switch() -> None:
    reader = Reader(_source(endpoints=FakeListing(history=(_history(),))))
    box = _box(reader, SharingPolicy(inventory=True, addresses=True))
    out = _json(_call(box, "get_aci_endpoint_history", address="10.193.101.4"))
    event = out["endpoints"][0]["events"][0]
    assert "description" not in event and event["code"] == "F1"
    assert "description" in out["withheld_fields"]


def test_history_unknown_address_bad_address_and_partial_reads() -> None:
    box = _box(Reader(_source(endpoints=FakeListing(history=()))))
    unknown = _json(_call(box, "get_aci_endpoint_history", address="10.9.9.9"))
    assert unknown["endpoints"] == [] and "no record" in unknown["message"]
    assert _call(box, "get_aci_endpoint_history", address="nope").is_error
    partial = _history(leaf_records_failed=1, events_unavailable=True)
    out = _json(
        _call(
            _box(Reader(_source(endpoints=FakeListing(history=(partial,))))),
            "get_aci_endpoint_history",
            address="10.193.101.4",
        )
    )
    assert out["endpoints"][0]["leaf_records_failed"] == 1
    assert out["endpoints"][0]["events_unavailable"] is True


def test_endpoint_listing_and_history_cost_two_slots() -> None:
    box = _box(Reader(_source(endpoints=FakeListing(history=(_history(),)))))
    for _ in range(aci_tools.RATE_ATTEMPTS // 2):
        assert not _call(box, "list_aci_endpoints", tenant="T").is_error
    assert _call(box, "get_aci_endpoint_history", address="10.193.101.4").is_error


def test_the_new_models_have_rules_for_every_field() -> None:
    from models import aci_endpoint

    names: set[str] = set()
    for cls in vars(aci_endpoint).values():
        if (
            isinstance(cls, type)
            and issubclass(cls, aci_endpoint._Endpoint)
            and cls is not aci_endpoint._Endpoint
        ):
            names |= set(cls.model_fields)
    assert names <= set(aci_fields.RULES), names - set(aci_fields.RULES)
