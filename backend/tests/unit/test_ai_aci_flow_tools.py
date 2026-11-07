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
