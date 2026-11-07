"""check_aci_connectivity: input, gates, evidence, cache, budget and the end-to-end verdicts."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from models.aci_endpoint import AciEndpoint
from models.aci_policy import (
    AciPolicyContract,
    AciPolicyFilter,
    AciPolicyFilterEntry,
    AciPolicySubject,
    AciVrfPolicy,
)
from services.aci.common.exceptions import AciAuthError
from services.aci.policy_service import AciPolicySnapshot
from services.ai_assistant.aci_reader import AciAccessError, AciSource
from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.providers.base import ToolCall
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.tools import aci_policy_tools, aci_tools
from services.ai_assistant.tools.aci_tools import ACI_READER_KEY, build_aci_tools
from services.ai_assistant.tools.base import Toolbox, ToolContext, ToolOutput
from services.ai_assistant.tools.playbook_tools import known_general_tool_names

ALL = SharingPolicy(inventory=True, addresses=True, content=True)
SECRET = "hunter2hunter2"
WEB_DN = "uni/tn-T/ap-AP/epg-web"
DB_DN = "uni/tn-T/ap-AP/epg-db"


def _ep(mac: str, ip: str, epg: str, vrf: str = "T/v1") -> AciEndpoint:
    return AciEndpoint(mac=mac, ips=(ip,), tenant="T", app_profile="AP", epg=epg, vrf=vrf)


WEB_EP = _ep("AA:BB:CC:00:00:01", "10.0.0.1", "web")
DB_EP = _ep("AA:BB:CC:00:00:02", "10.0.0.2", "db")
SQL = AciPolicyContract(
    tenant="T",
    name="sql",
    scope="context",
    subjects=(
        AciPolicySubject(
            name="s",
            filters=(
                AciPolicyFilter(
                    name="f",
                    tenant="T",
                    entries=(
                        AciPolicyFilterEntry(
                            name="e",
                            ether_type="ip",
                            protocol="tcp",
                            destination_port_from="1433",
                            destination_port_to="1433",
                        ),
                    ),
                ),
            ),
        ),
    ),
    provider_epgs=(DB_DN,),
    consumer_epgs=(WEB_DN,),
)
SNAP = AciPolicySnapshot(
    epgs={},
    contracts={("T", "sql"): SQL},
    vrfs={("T", "v1"): AciVrfPolicy(tenant="T", name="v1")},
)


class FakeFlowPolicy:
    def __init__(self, snapshot: AciPolicySnapshot = SNAP, error: Exception | None = None) -> None:
        self.snapshot_value, self.error, self.calls, self.kwargs = snapshot, error, 0, []

    async def snapshot(self, *, with_flow: bool = False) -> AciPolicySnapshot:
        self.calls += 1
        self.kwargs.append(with_flow)
        if self.error is not None:
            raise self.error
        return self.snapshot_value


class FakeFinder:
    def __init__(self, by_address: dict[str, tuple[AciEndpoint, ...]] | None = None) -> None:
        self.by_address = by_address or {
            "10.0.0.1": (WEB_EP,),
            "10.0.0.2": (DB_EP,),
        }
        self.calls: list[str] = []

    async def find(self, address: str):
        self.calls.append(address)
        return self.by_address.get(address, ())


class Reader:
    def __init__(self, *sources: AciSource, error: Exception | None = None) -> None:
        self._sources, self.error, self.calls = sources, error, 0

    async def sources(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self._sources


_counter = iter(range(10_000))


def _source(policy=None, finder=None, sid="fab") -> AciSource:
    return AciSource(
        sid,
        None,
        None,
        finder or FakeFinder(),
        None,
        policy or FakeFlowPolicy(),  # type: ignore[arg-type]
        cache_key=f"{sid}:{next(_counter)}",
    )


@pytest.fixture(autouse=True)
def _clean_cache():
    aci_policy_tools.POLICY_CACHE._entries.clear()
    aci_policy_tools.POLICY_CACHE._locks.clear()
    yield


def _box(reader: Reader, sharing: SharingPolicy = ALL, secrets: tuple[str, ...] = ()) -> Toolbox:
    redactor = Redactor()
    redactor.add_known_secrets(secrets)
    ctx = ToolContext(
        user_id=1, redactor=redactor, extras={ACI_READER_KEY: reader}, sharing=sharing
    )
    return Toolbox(build_aci_tools(), ctx)


def _call(box: Toolbox, **tool_input: Any) -> ToolOutput:
    return asyncio.run(
        box.execute(ToolCall(id="1", name="check_aci_connectivity", input=tool_input))
    )


def _json(out: ToolOutput) -> dict[str, Any]:
    assert not out.is_error, out.content
    return json.loads(out.content)


def _verdicts(out: dict[str, Any]) -> list[dict[str, Any]]:
    return [v for r in out["results"] for v in r["verdicts"]]


ASK = {"source_ip": "10.0.0.1", "destination_ip": "10.0.0.2", "protocol": "tcp", "port": 1433}


def test_a_permitted_flow_names_the_contract_and_the_epgs() -> None:
    out = _json(_call(_box(Reader(_source())), **ASK))
    (verdict,) = _verdicts(out)
    assert (verdict["verdict"], verdict["reason"]) == ("permitted", "contract_permits")
    assert (
        verdict["source"]["epg_path"] == "T/AP/web"
        and verdict["destination"]["epg_path"] == "T/AP/db"
    )
    assert verdict["contracts"][0]["matching_entries"] == ["tcp 1433"]
    assert "uni/tn-" not in json.dumps(out) and "packet trace" in out["limits"]
    assert out["question"] == {
        "source": "10.0.0.1",
        "destination": "10.0.0.2",
        "protocol": "tcp",
        "port": 1433,
        "verify_on_leaf": False,
    }


def test_the_wrong_port_and_the_wrong_direction_are_not_permitted() -> None:
    box = _box(Reader(_source()))
    wrong = _verdicts(_json(_call(box, **{**ASK, "port": 443})))[0]
    assert wrong["reason"] == "contract_wrong_port" and wrong["contracts"][0]["entries"] == [
        "tcp 1433"
    ]
    flipped = _verdicts(
        _json(_call(box, **{**ASK, "source_ip": "10.0.0.2", "destination_ip": "10.0.0.1"}))
    )[0]
    assert flipped["reason"] == "no_contract" and flipped["notes"]


def test_an_unlearned_address_is_unknown_not_an_error() -> None:
    out = _json(_call(_box(Reader(_source())), **{**ASK, "destination_ip": "10.9.9.9"}))
    (verdict,) = _verdicts(out)
    assert (verdict["verdict"], verdict["reason"]) == ("unknown", "destination_not_found")


def test_icmp_needs_no_port_and_tcp_needs_one() -> None:
    box = _box(Reader(_source()))
    assert _call(box, source_ip="10.0.0.1", destination_ip="10.0.0.2", protocol="tcp").is_error
    assert _call(box, **{**ASK, "protocol": "icmp"}).is_error  # a port with icmp
    out = _json(_call(box, source_ip="10.0.0.1", destination_ip="10.0.0.2", protocol="icmp"))
    assert _verdicts(out)[0]["reason"] == "contract_wrong_port"  # sql has no icmp entry


@pytest.mark.parametrize(
    "bad",
    [
        {"source_ip": "x"},
        {"destination_ip": "10.0.0"},
        {"port": 0},
        {"port": 70000},
        {"protocol": "gre"},
    ],
)
def test_bad_input_sends_nothing(bad: dict[str, Any]) -> None:
    reader = Reader(_source())
    assert _call(_box(reader), **{**ASK, **bad}).is_error and reader.calls == 0


@pytest.mark.parametrize(
    "sharing", [SharingPolicy(), SharingPolicy(inventory=True), SharingPolicy(addresses=True)]
)
def test_both_switches_gate_the_call_before_any_request(sharing: SharingPolicy) -> None:
    finder, policy = FakeFinder(), FakeFlowPolicy()
    reader = Reader(_source(policy, finder))
    out = _call(_box(reader, sharing), **ASK)
    assert "not_shared" in out.content and reader.calls == 0
    assert finder.calls == [] and policy.calls == 0


def test_the_policy_is_read_with_the_flow_switches_and_cached_under_its_own_key() -> None:
    policy = FakeFlowPolicy()
    box = _box(Reader(_source(policy)))
    _json(_call(box, **ASK))
    _json(_call(box, **{**ASK, "port": 443}))
    assert policy.calls == 1 and policy.kwargs == [True]


def test_the_permission_is_asked_before_the_cache_is_read() -> None:
    policy = FakeFlowPolicy()
    source = _source(policy)
    _json(_call(_box(Reader(source)), **ASK))
    out = _call(_box(Reader(source, error=AciAccessError())), **ASK)
    assert out.is_error and "lacks the permission" in out.content and policy.calls == 1


def test_one_failing_source_is_a_fixed_sentence_and_all_failing_is_an_error() -> None:
    bad = _source(FakeFlowPolicy(error=AciAuthError(f"401 {SECRET}")), sid="b")
    out = _json(_call(_box(Reader(_source(sid="a"), bad)), **ASK))
    assert out["source_errors"][0]["source_id"] == "b" and SECRET not in json.dumps(out)
    only_bad = _call(_box(Reader(bad)), **ASK)
    assert only_bad.is_error and SECRET not in only_bad.content


def test_a_flow_check_costs_three_slots_of_the_budget() -> None:
    box = _box(Reader(_source()))
    assert aci_tools.RATE_ATTEMPTS == 20  # 20 slots / 3 per check = 6 checks, the 7th is refused
    for _ in range(6):
        assert not _call(box, **ASK).is_error
    assert _call(box, **ASK).is_error


def test_names_from_the_fabric_are_redacted() -> None:
    odd = _ep("AA:BB:CC:00:00:03", "10.0.0.3", f"web-{SECRET}")
    finder = FakeFinder({"10.0.0.3": (odd,), "10.0.0.2": (DB_EP,)})
    out = _call(
        _box(Reader(_source(finder=finder)), secrets=(SECRET,)),
        **{**ASK, "source_ip": "10.0.0.3"},
    )
    assert SECRET not in out.content


def test_several_endpoints_for_one_address_give_one_verdict_each_and_are_capped() -> None:
    twins = tuple(_ep(f"AA:BB:CC:00:00:0{i}", "10.0.0.1", "web") for i in range(1, 5))
    finder = FakeFinder({"10.0.0.1": twins, "10.0.0.2": (DB_EP,)})
    out = _json(_call(_box(Reader(_source(finder=finder))), **ASK))
    assert len(_verdicts(out)) == 3


def test_registered_for_playbooks_and_read_only() -> None:
    assert "check_aci_connectivity" in known_general_tool_names()
    assert "check_aci_connectivity" in {t.name for t in build_aci_tools()}


def test_every_flow_model_field_has_a_rule() -> None:
    from models import aci_flow
    from services.ai_assistant.tools import aci_fields

    names: set[str] = set()
    for cls in vars(aci_flow).values():
        if isinstance(cls, type) and issubclass(cls, aci_flow._Flow) and cls is not aci_flow._Flow:
            names |= set(cls.model_fields)
    unruled = names - set(aci_fields.RULES) - aci_fields.EXCLUDED
    assert not unruled, unruled


# -- verify_on_leaf: the zoning rules of the hosts' leaves --------------------------------------


def _tagged_snapshot() -> AciPolicySnapshot:
    from models.aci_policy import AciPolicyEpg

    return AciPolicySnapshot(
        epgs={
            WEB_DN: AciPolicyEpg(
                epg_dn=WEB_DN, tenant="T", app_profile="AP", epg="web", pc_tag="100"
            ),
            DB_DN: AciPolicyEpg(epg_dn=DB_DN, tenant="T", app_profile="AP", epg="db", pc_tag="200"),
        },
        contracts={("T", "sql"): SQL},
        vrfs={("T", "v1"): AciVrfPolicy(tenant="T", name="v1")},
    )


def _on(ep: AciEndpoint, *nodes: int) -> AciEndpoint:
    from models.aci_endpoint import AciEndpointAttachment

    attachments = (AciEndpointAttachment(pod_id=1, node_ids=nodes, interface="eth1/1"),)
    return ep.model_copy(update={"attachments": attachments})


class FakeLeafDetails:
    """Zoning rules of the leaves: scope 55 is T:v1, tag 100 -> 200 on tcp/1433 (or a deny)."""

    def __init__(self, action: str = "permit", fail: set[int] | None = None) -> None:
        self.action, self.fail = action, fail or set()
        self.contract_calls: list[int] = []

    async def get_contracts(self, pod_id: int, node_id: int):
        from models.aci_facts import AciContractRule, AciContracts, AciFilterEntry

        self.contract_calls.append(node_id)
        if node_id in self.fail:
            raise AciAuthError(f"401 {SECRET}")
        rule = AciContractRule(
            scope="55",
            source_pc_tag="100",
            destination_pc_tag="200",
            filter_id="7",
            action=self.action,
            direction="bi-dir",
            priority="fully_qual",
            state="enabled",
        )
        entry = AciFilterEntry(
            filter_id="7",
            ether_type="ip",
            protocol="tcp",
            destination_port_from="1433",
            destination_port_to="1433",
        )
        return AciContracts(rules=(rule,), filters=(entry,))

    async def get_vrf_scopes(self, pod_id: int, node_id: int):
        return {"T/v1": "55"}


def _verify_source(details: FakeLeafDetails, finder: FakeFinder | None = None) -> AciSource:
    finder = finder or FakeFinder({"10.0.0.1": (_on(WEB_EP, 101),), "10.0.0.2": (_on(DB_EP, 102),)})
    return AciSource(
        "fab",
        None,
        details,
        finder,
        None,
        FakeFlowPolicy(_tagged_snapshot()),  # type: ignore[arg-type]
        cache_key=f"fab:{next(_counter)}",
    )


VERIFY = {**ASK, "verify_on_leaf": True}


def test_the_leaves_rules_agree_with_the_contract_intent() -> None:
    details = FakeLeafDetails()
    out = _json(_call(_box(Reader(_verify_source(details))), **VERIFY))
    (verdict,) = _verdicts(out)
    assert verdict["verdict"] == "permitted" and verdict["programmed_summary"] == "permit"
    assert "enforce what the contracts intend" in verdict["programmed_note"]
    assert sorted(c["node_id"] for c in verdict["programmed"]) == [101, 102]
    leaf = verdict["programmed"][0]
    assert leaf["rule"]["filter_id"] == "7" and leaf["entries"] == ["tcp 1433"]
    assert out["question"]["verify_on_leaf"] is True


def test_a_leaf_that_denies_what_the_contracts_permit_is_called_out() -> None:
    out = _json(_call(_box(Reader(_verify_source(FakeLeafDetails("deny")))), **VERIFY))
    verdict = _verdicts(out)[0]
    assert verdict["verdict"] == "permitted" and verdict["programmed_summary"] == "deny"
    assert verdict["programmed_note"].startswith("Differs")


def test_without_the_flag_no_leaf_is_read() -> None:
    details = FakeLeafDetails()
    verdict = _verdicts(_json(_call(_box(Reader(_verify_source(details))), **ASK)))[0]
    assert details.contract_calls == [] and verdict["programmed"] == []
    assert "programmed_summary" not in verdict


def test_a_flow_that_could_not_be_placed_reads_no_leaf() -> None:
    details = FakeLeafDetails()
    out = _json(
        _call(_box(Reader(_verify_source(details))), **{**VERIFY, "destination_ip": "10.9.9.9"})
    )
    assert _verdicts(out)[0]["reason"] == "destination_not_found" and details.contract_calls == []


def test_a_failing_leaf_is_flagged_and_the_summary_is_partial_not_permit() -> None:
    details = FakeLeafDetails(fail={101})
    out = _json(_call(_box(Reader(_verify_source(details))), **VERIFY))
    verdict = _verdicts(out)[0]
    outcomes = {c["node_id"]: c["outcome"] for c in verdict["programmed"]}
    assert outcomes == {101: "unreadable", 102: "permit"}
    # One leaf could not be read (and enforcement is usually at the source's leaf): not a permit.
    assert verdict["programmed_summary"] == "partial"
    assert "Only some leaves answered" in verdict["programmed_note"]
    assert SECRET not in json.dumps(out)


def test_each_leaf_is_read_once_however_many_verdicts_need_it() -> None:
    twins = tuple(_on(_ep(f"AA:BB:CC:00:00:0{i}", "10.0.0.1", "web"), 101) for i in range(1, 4))
    finder = FakeFinder({"10.0.0.1": twins, "10.0.0.2": (_on(DB_EP, 102),)})
    details = FakeLeafDetails()
    out = _json(_call(_box(Reader(_verify_source(details, finder))), **VERIFY))
    assert len(_verdicts(out)) == 3 and sorted(details.contract_calls) == [101, 102]


def test_an_outside_address_has_no_leaf_so_the_rules_are_not_read() -> None:
    from models.aci_policy import AciExternalEpg, AciExternalSubnet, AciPolicyL3Out

    l3out = AciPolicyL3Out(
        tenant="T",
        name="corp",
        vrf="v1",
        external_epgs=(
            AciExternalEpg(
                epg_dn="uni/tn-T/out-corp/instP-all",
                name="all",
                pc_tag="15",
                subnets=(AciExternalSubnet(ip="0.0.0.0/0", scope=("import-security",)),),
            ),
        ),
    )
    snap = _tagged_snapshot()
    snap = AciPolicySnapshot(
        snap.epgs, snap.contracts, {("T", "corp"): l3out}, snap.vrfs, snap.flags
    )
    source = AciSource(
        "fab",
        None,
        FakeLeafDetails(),
        FakeFinder({"10.0.0.1": (_on(WEB_EP, 101),)}),
        None,
        FakeFlowPolicy(snap),
        cache_key=f"fab:{next(_counter)}",  # type: ignore[arg-type]
    )
    out = _json(_call(_box(Reader(source)), **{**VERIFY, "destination_ip": "8.8.8.8"}))
    verdict = _verdicts(out)[0]
    # The outside side has no leaf; the one leaf that is read (the source's) has no rule towards
    # the external EPG's tag, so there is no hardware answer.
    assert verdict["programmed_summary"] == "unavailable"
    assert [(c["node_id"], c["outcome"]) for c in verdict["programmed"]] == [(101, "no_rule")]


def test_verifying_costs_five_slots_and_one_more_for_every_leaf_read() -> None:
    box = _box(Reader(_verify_source(FakeLeafDetails())))
    assert aci_tools.RATE_ATTEMPTS == 20  # 3 + 2 + 2 leaves = 7 slots per verified call
    for _ in range(2):
        out = _json(_call(box, **VERIFY))
        assert _verdicts(out)[0]["programmed_summary"] == "permit"
    # 6 slots are left: the call itself (5) is allowed, its two leaves (2 more) are not.
    third = _json(_call(box, **VERIFY))
    assert _verdicts(third)[0]["programmed_summary"] == "unavailable"
    assert _call(box, **VERIFY).is_error  # 1 slot left: not even the call


def test_when_the_leaves_do_not_fit_the_budget_they_are_not_read_and_it_says_so() -> None:
    details = FakeLeafDetails()
    box = _box(Reader(_verify_source(details)))
    for _ in range(5):  # 5 plain checks use 15 of the 20 slots
        assert not _call(box, **ASK).is_error
    # The verified call's base cost (5) still fits; the two leaves (2 more) do not.
    out = _json(_call(box, **VERIFY))
    verdict = _verdicts(out)[0]
    assert details.contract_calls == []
    assert verdict["programmed_summary"] == "unavailable"
    assert "budget" in verdict["programmed_note"] and verdict["verdict"] == "permitted"


def test_more_than_four_leaves_are_counted_as_skipped_and_the_summary_is_partial() -> None:
    finder = FakeFinder(
        {"10.0.0.1": (_on(WEB_EP, 101, 102, 103),), "10.0.0.2": (_on(DB_EP, 104, 105, 106),)}
    )
    details = FakeLeafDetails()
    out = _json(_call(_box(Reader(_verify_source(details, finder))), **VERIFY))
    verdict = _verdicts(out)[0]
    assert sorted(details.contract_calls) == [101, 102, 103, 104]
    assert verdict["programmed_leaves_skipped"] == 2 and verdict["programmed_summary"] == "partial"


def test_the_limits_of_the_leaf_check_travel_with_its_answer() -> None:
    out = _json(_call(_box(Reader(_verify_source(FakeLeafDetails()))), **VERIFY))
    assert "priority" in out["programmed_limits"] and "unsure" in out["programmed_limits"]
    plain = _json(_call(_box(Reader(_source())), **ASK))
    assert "programmed_limits" not in plain
