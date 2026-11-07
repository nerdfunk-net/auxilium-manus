"""ACI EPG, contract and L3Out tools for Ask the Net: gates, cache order, answers, wiring."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from models import aci_policy
from models.aci_policy import (
    AciExternalEpg,
    AciExternalSubnet,
    AciL3OutInterface,
    AciL3OutNode,
    AciPolicyL3Out,
)
from services.aci.common.exceptions import AciAuthError
from services.aci.policy_service import AciPolicySnapshot
from services.ai_assistant.aci_reader import AciAccessError, AciSource
from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.providers.base import ToolCall
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.tools import aci_fields, aci_policy_tools, aci_tools
from services.ai_assistant.tools.aci_tools import ACI_READER_KEY, build_aci_tools
from services.ai_assistant.tools.base import Toolbox, ToolContext, ToolOutput
from services.ai_assistant.tools.playbook_tools import known_general_tool_names
from tests.unit.test_aci_policy_search import APP, DB, SNAP, WEB

ALL = SharingPolicy(inventory=True, addresses=True, content=True)
INVENTORY_ONLY = SharingPolicy(inventory=True)
NOTHING = SharingPolicy()

L3OUT = AciPolicyL3Out(
    tenant="T",
    name="ext",
    vrf="vrf1",
    protocols=("bgp",),
    nodes=(AciL3OutNode(pod_id=1, node_id=101, router_id="10.1.100.1"),),
    interfaces=(
        AciL3OutInterface(pod_id=1, node_ids=(101,), interface="eth1/47", address="10.1.200.1/31"),
    ),
    external_epgs=(
        AciExternalEpg(
            epg_dn="uni/tn-T/out-ext/instP-x",
            name="x",
            subnets=(AciExternalSubnet(ip="0.0.0.0/0", scope=("import-security",)),),
            consumed=("common/web",),
        ),
    ),
)
SNAP3 = AciPolicySnapshot(SNAP.epgs, SNAP.contracts, {("T", "ext"): L3OUT})


class FakePolicy:
    def __init__(self, snapshot: AciPolicySnapshot = SNAP3, error: Exception | None = None) -> None:
        self.snapshot_value, self.error, self.calls = snapshot, error, 0

    async def snapshot(self) -> AciPolicySnapshot:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.snapshot_value


class Reader:
    def __init__(self, *sources: AciSource, error: Exception | None = None) -> None:
        self._sources, self.error, self.calls = sources, error, 0

    async def sources(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self._sources


_counter = iter(range(10_000))


def _source(policy: FakePolicy | None = None, sid: str = "fab") -> AciSource:
    return AciSource(
        sid,
        None,
        None,
        None,
        None,
        policy or FakePolicy(),
        cache_key=f"{sid}:{next(_counter)}",  # type: ignore[arg-type]
    )


@pytest.fixture(autouse=True)
def _clean_cache():
    aci_policy_tools.POLICY_CACHE._entries.clear()
    aci_policy_tools.POLICY_CACHE._locks.clear()
    yield


def _box(reader: Reader, sharing: SharingPolicy = ALL) -> Toolbox:
    ctx = ToolContext(
        user_id=1, redactor=Redactor(), extras={ACI_READER_KEY: reader}, sharing=sharing
    )
    return Toolbox(build_aci_tools(), ctx)


def _call(box: Toolbox, tool: str, /, **tool_input: Any) -> ToolOutput:
    return asyncio.run(box.execute(ToolCall(id="1", name=tool, input=tool_input)))


def _json(out: ToolOutput) -> dict[str, Any]:
    assert not out.is_error, out.content
    return json.loads(out.content)


# -- epgs --------------------------------------------------------------------------------------


def test_search_epgs_rows_counts_and_age() -> None:
    out = _json(_call(_box(Reader(_source())), "search_aci_epgs", provides="sql"))
    assert out["total"] == 1 and out["epgs"][0]["epg"] == "db"
    assert out["epgs"][0]["provided_contracts"] == 1 and out["as_of_seconds_ago"] == {"fab": 0}


def test_search_epgs_pages() -> None:
    out = _json(_call(_box(Reader(_source())), "search_aci_epgs", limit=2, offset=1))
    assert out["total"] == 4 and len(out["epgs"]) == 2 and out["has_more"]


def test_get_epg_found_and_miss_with_closest_names() -> None:
    box = _box(Reader(_source()))
    out = _json(_call(box, "get_aci_epg", tenant="T", app_profile="AP", epg="web"))
    assert out["epgs"][0]["provided"] == ["common/web"] and out["epgs"][0]["consumed"] == [
        "common/sql"
    ]
    miss = _json(_call(box, "get_aci_epg", tenant="T", app_profile="AP", epg="wbe"))
    assert miss["found"] is False and "web" in miss["closest_epg_names"]


# -- contracts ---------------------------------------------------------------------------------


def test_search_contracts_by_port() -> None:
    box = _box(Reader(_source()))
    out = _json(_call(box, "search_aci_contracts", protocol="tcp", port=1433))
    assert [c["name"] for c in out["contracts"]] == ["default", "sql"]
    assert "vzAny" in out["note"]
    out = _json(_call(box, "search_aci_contracts", provided_by="T/AP/db"))
    assert [c["name"] for c in out["contracts"]] == ["sql"]


def test_port_without_protocol_is_rejected() -> None:
    assert _call(_box(Reader(_source())), "search_aci_contracts", port=80).is_error


def test_get_contract_names_epgs_never_dns() -> None:
    out = _call(_box(Reader(_source())), "get_aci_contract", tenant="common", name="sql")
    data = _json(out)
    contract = data["contracts"][0]
    assert contract["provider_epgs"] == ["T/AP/db"]
    assert set(contract["consumer_epgs"]) == {"T/AP/web", "T/AP/app"}
    assert "uni/tn-" not in out.content
    entry = contract["subjects"][0]["filters"][0]["entries"][0]
    assert entry["protocol"] == "tcp" and entry["destination_port_from"] == "1433"


def test_get_contract_miss_lists_closest() -> None:
    out = _json(_call(_box(Reader(_source())), "get_aci_contract", tenant="common", name="sq"))
    assert out["found"] is False and "sql" in out["closest_contract_names"]


# -- between -----------------------------------------------------------------------------------


def test_between_both_directions_and_limits() -> None:
    box = _box(Reader(_source()))
    out = _json(_call(box, "find_aci_contracts_between", epg_a="T/AP/web", epg_b="T/AP/db"))
    result = out["results"][0]
    assert result["a_provides_b_consumes"] == []
    assert [c["name"] for c in result["b_provides_a_consumes"]] == ["sql"]
    assert "vzAny" in out["limits"] and "message" not in out
    flipped = _json(_call(box, "find_aci_contracts_between", epg_a="T/AP/db", epg_b="T/AP/web"))
    assert [c["name"] for c in flipped["results"][0]["a_provides_b_consumes"]] == ["sql"]


def test_between_none_is_an_answer_ambiguity_and_unknown_are_errors() -> None:
    box = _box(Reader(_source()))
    none = _json(_call(box, "find_aci_contracts_between", epg_a="T/AP/web", epg_b="U/AP2/db"))
    assert "No contract links" in none["message"]
    ambiguous = _call(box, "find_aci_contracts_between", epg_a="web", epg_b="db")
    assert ambiguous.is_error and "ambiguous" in ambiguous.content
    assert _call(box, "find_aci_contracts_between", epg_a="web", epg_b="zzz").is_error


# -- l3outs ------------------------------------------------------------------------------------


def test_l3outs_with_and_without_addresses() -> None:
    full = _json(_call(_box(Reader(_source())), "list_aci_l3outs", node=101))
    out = full["l3outs"][0]
    assert out["vrf"] == "vrf1" and out["nodes"][0]["router_id"] == "10.1.100.1"
    assert out["interfaces"][0]["address"] == "10.1.200.1/31"
    assert out["external_epgs"][0]["subnets"][0]["ip"] == "0.0.0.0/0"
    assert "epg_dn" not in json.dumps(full)
    names = _json(_call(_box(Reader(_source()), INVENTORY_ONLY), "list_aci_l3outs"))
    flat = json.dumps(names)
    assert "10.1.100.1" not in flat and "10.1.200.1" not in flat and "0.0.0.0" not in flat
    assert {"router_id", "address", "ip"} <= set(names["withheld_fields"])
    assert _json(_call(_box(Reader(_source())), "list_aci_l3outs", node=999))["total"] == 0


# -- gates, cache order, errors ----------------------------------------------------------------

TOOLS = [
    ("search_aci_epgs", {}),
    ("get_aci_epg", {"tenant": "T", "app_profile": "AP", "epg": "web"}),
    ("search_aci_contracts", {}),
    ("get_aci_contract", {"tenant": "common", "name": "sql"}),
    ("find_aci_contracts_between", {"epg_a": "T/AP/web", "epg_b": "T/AP/db"}),
    ("list_aci_l3outs", {}),
]


@pytest.mark.parametrize("tool,args", TOOLS)
def test_no_inventory_switch_sends_nothing(tool: str, args: dict[str, Any]) -> None:
    policy = FakePolicy()
    reader = Reader(_source(policy))
    out = _call(_box(reader, NOTHING), tool, **args)
    assert "not_shared" in out.content and reader.calls == 0 and policy.calls == 0


def test_the_permission_is_checked_before_the_cache_is_read() -> None:
    policy = FakePolicy()
    source = _source(policy)
    _json(_call(_box(Reader(source)), "search_aci_epgs"))  # warms the cache
    assert policy.calls == 1
    denied = _call(_box(Reader(source, error=AciAccessError())), "search_aci_epgs")
    assert denied.is_error and "lacks the permission" in denied.content
    assert policy.calls == 1  # and the denied call did not even look at the cache


def test_the_cache_serves_repeat_calls_and_fabrics_do_not_mix() -> None:
    first, second = FakePolicy(), FakePolicy(AciPolicySnapshot({}, {}))
    a, b = _source(first, "a"), _source(second, "b")
    box = _box(Reader(a, b))
    out = _json(_call(box, "search_aci_epgs"))
    _call(box, "get_aci_epg", tenant="T", app_profile="AP", epg="web")
    assert first.calls == 1 and second.calls == 1
    assert {e["source_id"] for e in out["epgs"]} == {"a"}


def test_one_failing_source_is_a_fixed_sentence_and_all_failing_is_an_error() -> None:
    secret = "hunter2hunter2"
    bad = _source(FakePolicy(error=AciAuthError(f"401 {secret}")), "b")
    out = _json(_call(_box(Reader(_source(sid="a"), bad)), "search_aci_epgs"))
    assert out["source_errors"][0]["source_id"] == "b" and secret not in json.dumps(out)
    only_bad = _call(_box(Reader(bad)), "search_aci_epgs")
    assert only_bad.is_error and secret not in only_bad.content


def test_reader_errors_pass_through() -> None:
    out = _call(_box(Reader(error=AciAccessError())), "list_aci_l3outs")
    assert out.is_error


# -- field rules and wiring --------------------------------------------------------------------


def test_every_policy_model_field_has_a_rule_or_is_excluded() -> None:
    names: set[str] = set()
    for cls in vars(aci_policy).values():
        if (
            isinstance(cls, type)
            and issubclass(cls, aci_policy._Policy)
            and cls is not aci_policy._Policy
        ):
            names |= set(cls.model_fields)
    assert not (names - set(aci_fields.RULES) - aci_fields.EXCLUDED)


def test_tools_are_registered_and_read_only() -> None:
    expected = {t for t, _ in TOOLS}
    assert expected <= known_general_tool_names()
    assert expected <= {t.name for t in build_aci_tools()}
    assert all(
        t.name.split("_")[0] in {"find", "list", "get", "search", "check"}
        for t in build_aci_tools()
    )


def test_unused_epg_fixtures_exist() -> None:
    assert WEB and APP and DB


# -- include_deployed_on -----------------------------------------------------------------------


class _Leaf:
    def __init__(self, node: int, role: str = "leaf") -> None:
        self.node_id, self.name, self.role, self.pod_id = node, f"leaf-{node}", role, 1


class _Details:
    """Leaf 101 and 102 carry web (two encaps on 101); 103 fails; 104 carries only app."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    async def get_epgs(self, pod: int, node: int):
        from models.aci_facts import AciEpg

        self.calls.append(node)
        if node == 103:
            raise AciAuthError("401 hunter2hunter2")
        mine = {101: ("vlan-10", "vlan-11"), 102: ("vlan-10",)}.get(node, ())
        rows = [AciEpg(epg_dn=WEB.epg_dn, encap=e, state="up") for e in mine]
        if node == 104:
            rows = [AciEpg(epg_dn=APP.epg_dn, encap="vlan-5")]
        return tuple(rows)


class _Devices:
    def __init__(self, leaves: list[_Leaf]) -> None:
        self.leaves, self.calls = leaves, 0

    async def search(self):
        self.calls += 1
        return self.leaves


def _deploy_source(leaves: list[_Leaf]) -> tuple[AciSource, _Details, _Devices]:
    details, devices = _Details(), _Devices(leaves)
    source = AciSource(
        "fab",
        devices,
        details,
        None,
        None,
        FakePolicy(),
        cache_key=f"fab:{next(_counter)}",  # type: ignore[arg-type]
    )
    return source, details, devices


def test_deployed_on_is_off_by_default_and_reads_no_leaf() -> None:
    source, details, devices = _deploy_source([_Leaf(101)])
    out = _json(_call(_box(Reader(source)), "get_aci_epg", tenant="T", app_profile="AP", epg="web"))
    assert "deployed_on" not in out["epgs"][0] and details.calls == [] and devices.calls == 0


def test_deployed_on_lists_carrying_leaves_and_counts_failures() -> None:
    source, details, _ = _deploy_source(
        [_Leaf(101), _Leaf(102), _Leaf(103), _Leaf(104), _Leaf(201, "spine")]
    )
    out = _json(
        _call(
            _box(Reader(source)),
            "get_aci_epg",
            tenant="T",
            app_profile="AP",
            epg="web",
            include_deployed_on=True,
        )
    )
    deployed = out["epgs"][0]["deployed_on"]
    assert [leaf["node_id"] for leaf in deployed["leaves"]] == [101, 102]
    assert deployed["leaves"][0]["encaps"] == ["vlan-10", "vlan-11"]
    assert deployed["leaves_failed"] == 1 and deployed["leaves_checked"] == 3
    assert 201 not in details.calls  # a spine is never read
    assert "hunter2hunter2" not in json.dumps(out)


def test_deployed_on_is_bounded() -> None:
    leaves = [_Leaf(100 + i) for i in range(aci_policy_tools.MAX_DEPLOYED_LEAVES + 7)]
    source, details, _ = _deploy_source(leaves)
    out = _json(
        _call(
            _box(Reader(source)),
            "get_aci_epg",
            tenant="T",
            app_profile="AP",
            epg="web",
            include_deployed_on=True,
        )
    )
    assert len(details.calls) == aci_policy_tools.MAX_DEPLOYED_LEAVES
    assert out["epgs"][0]["deployed_on"]["leaves_not_checked"] == 7


def test_deployed_on_uses_one_rate_budget_slot() -> None:
    source, _, _ = _deploy_source([_Leaf(101)])
    reader = Reader(source)
    _json(
        _call(
            _box(reader),
            "get_aci_epg",
            tenant="T",
            app_profile="AP",
            epg="web",
            include_deployed_on=True,
        )
    )
    assert reader.calls == 1


# -- review findings ---------------------------------------------------------------------------


def test_l3outs_page_with_limit_and_offset() -> None:
    many = {
        ("T", f"out{i:02d}"): AciPolicyL3Out(tenant="T", name=f"out{i:02d}", vrf="v")
        for i in range(25)
    }
    snap = AciPolicySnapshot({}, {}, many)
    box = _box(Reader(_source(FakePolicy(snap))))
    first = _json(_call(box, "list_aci_l3outs"))
    assert first["total"] == 25 and len(first["l3outs"]) == 20 and first["has_more"]
    rest = _json(_call(box, "list_aci_l3outs", offset=20))
    assert [o["name"] for o in rest["l3outs"]] == [f"out{i:02d}" for i in range(20, 25)]
    assert not rest["has_more"]


def test_between_errors_are_redacted() -> None:
    secret = "hunter2hunter2"
    odd = _epg_named(f"web-{secret}", "X")
    other = _epg_named(f"web-{secret}", "Y")
    snap = AciPolicySnapshot({e.epg_dn: e for e in (odd, other)}, {})
    redactor = Redactor()
    redactor.add_known_secrets((secret,))
    ctx = ToolContext(
        user_id=1,
        redactor=redactor,
        extras={ACI_READER_KEY: Reader(_source(FakePolicy(snap)))},
        sharing=ALL,
    )
    out = _call(
        Toolbox(build_aci_tools(), ctx),
        "find_aci_contracts_between",
        epg_a=f"web-{secret}",
        epg_b="zzz",
    )
    assert out.is_error and secret not in out.content


def _epg_named(name: str, tenant: str):
    from tests.unit.test_aci_policy_search import _epg

    return _epg(tenant, "AP", name)


def test_a_leaf_walk_costs_five_slots() -> None:
    source, _, _ = _deploy_source([_Leaf(101)])
    box = _box(Reader(source))
    args = {"tenant": "T", "app_profile": "AP", "epg": "web", "include_deployed_on": True}
    assert aci_tools.RATE_ATTEMPTS == 20  # 20 slots / 5 per leaf walk = 4 walks, the 5th is refused
    for _ in range(4):
        assert not _call(box, "get_aci_epg", **args).is_error
    assert _call(box, "get_aci_epg", **args).is_error
