"""The leaf's zoning rules: priority classes, undecided cases, disabled rules, partial answers."""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from typing import Any

import pytest

from models.aci_facts import AciContractRule, AciContracts, AciFilterEntry
from models.aci_flow import AciFlowLeaf, AciFlowLeafCheck, AciFlowParty, AciFlowVerdict
from services.aci.common.exceptions import AciAPIError
from services.aci.details_service import AciDetailsService
from services.aci.zoning import (
    MAX_ZONING_LEAVES,
    PRIORITY_RANK,
    attach_programmed,
    check_leaf,
    epg_tag,
    evaluate_leaf,
    leaves_to_check,
    summarize,
)
from tests.unit.test_aci_details_service import leaf_client

DATA = json.loads((Path(__file__).parent / "fixtures" / "aci_zoning_sandbox.json").read_text())
SCOPE = "2523136"  # VY-TN:VY-VRF on the sandbox leaf
EPG2, VY = "49154", "32771"  # EPG2 consumes https from VY-EPG; real tags of the fixture


def _rows(state: str | None) -> list[dict[str, Any]]:
    """The real rules; ``state`` replaces ``operSt`` (a real leaf says ``enabled``)."""
    rows = copy.deepcopy(DATA["actrlRule"])
    if state is not None:
        for row in rows:
            row["operSt"] = state
    return rows


async def _contracts(state: str | None = "enabled") -> AciContracts:
    client = leaf_client(data={"actrlRule": _rows(state), "actrlEntry": DATA["actrlEntry"]})
    return await AciDetailsService(client, None).get_contracts(1, 101)  # type: ignore[arg-type]


def _real(src, dst, protocol="tcp", port=443, state: str | None = "enabled", scope=SCOPE):
    contracts = asyncio.run(_contracts(state))
    return evaluate_leaf(
        contracts.rules,
        contracts.filters,
        scope=scope,
        src_tag=src,
        dst_tag=dst,
        protocol=protocol,
        port=port,
    )


def _rule(src, dst, flt, action="permit", prio="fully_qual", direction="uni-dir", state="enabled"):
    return AciContractRule(
        scope=SCOPE,
        source_pc_tag=src,
        destination_pc_tag=dst,
        filter_id=flt,
        action=action,
        direction=direction,
        priority=prio,
        state=state,
    )


def _entry(flt, proto="tcp", dport=None, sport=None, ether="ip", dto=None, sto=None):
    return AciFilterEntry(
        filter_id=flt,
        ether_type=ether,
        protocol=proto,
        destination_port_from=dport,
        destination_port_to=dto or dport,
        source_port_from=sport,
        source_port_to=sto or sport,
    )


def _decide(rules, filters, src="1", dst="2", protocol="tcp", port=80):
    return evaluate_leaf(
        rules, filters, scope=SCOPE, src_tag=src, dst_tag=dst, protocol=protocol, port=port
    )


IMPLICIT_DENY = _rule("any", "any", "implicit", "deny,log", prio="any_any_any")


# -- real rows of a DevNet leaf (made `enabled`, as on a real switch) --------------------------


def test_the_consumer_may_reach_the_provider_on_the_filtered_port() -> None:
    decision = _real(EPG2, VY, port=443)
    assert decision.outcome == "permit" and decision.rule is not None
    assert (decision.rule.filter_id, decision.rule.priority) == ("9", "fully_qual")
    assert decision.entries[0].destination_port_from == "https"


def test_another_port_falls_through_to_the_implicit_deny() -> None:
    decision = _real(EPG2, VY, port=22)
    assert decision.outcome == "deny" and decision.rule is not None
    assert decision.rule.filter_id == "implicit"


def test_the_provider_cannot_open_a_connection_to_the_consumer() -> None:
    # The only rule in that direction is the reverse leg (uni-dir-ignore, matched by source port).
    decision = _real(VY, EPG2, port=443)
    assert decision.outcome == "deny" and decision.rule is not None
    assert decision.rule.filter_id == "implicit"


def test_a_wildcard_source_rule_to_the_bridge_domain_flood_tag_permits() -> None:
    decision = _real("5555", "32770", port=80)
    assert decision.outcome == "permit" and decision.rule is not None
    assert decision.rule.priority == "src_dst_any"


def test_another_vrf_scope_has_its_own_rules_and_an_unknown_scope_none() -> None:
    other = _real(EPG2, VY, scope="16777200")
    assert other.outcome == "deny" and other.rule is not None and other.rule.scope == "16777200"
    assert _real(EPG2, VY, scope="1").outcome is None


def test_the_rules_as_the_simulated_switch_reports_them_are_not_enforced() -> None:
    # Every real row of the sandbox has operSt=disabled: nothing is installed.
    decision = _real(EPG2, VY, state=None)
    assert decision.outcome is None and decision.only_disabled


# -- finding 1: the priority class decides, not the count of exact tags or the action ----------


def test_a_filtered_any_any_permit_beats_the_implicit_deny_in_either_listing_order() -> None:
    vzany = _rule("any", "any", "f1", "permit", prio="any_any_filter")
    for rules in ([vzany, IMPLICIT_DENY], [IMPLICIT_DENY, vzany]):
        decision = _decide(rules, [_entry("f1", dport="80")])
        assert decision.outcome == "permit" and decision.rule is not None
        assert decision.rule.filter_id == "f1"


def test_a_one_tag_permit_beats_a_one_tag_vrf_deny_with_the_same_destination() -> None:
    permit = _rule("any", "2", "f1", "permit", prio="any_dest_filter")
    deny = _rule("any", "2", "implicit", "deny,log", prio="any_vrf_any_deny")
    for rules in ([permit, deny], [deny, permit]):
        assert _decide(rules, [_entry("f1", dport="80")]).outcome == "permit"


def test_the_priority_numbers_order_the_classes_like_the_leaf() -> None:
    order = sorted(PRIORITY_RANK, key=PRIORITY_RANK.get)  # type: ignore[arg-type]
    assert order[:2] == ["fully_qual", "src_dst_any"]
    assert order.index("any_any_filter") < order.index("any_any_any")
    assert order.index("grp_src_any_any_deny") < order.index("grp_any_any_any_permit")


def test_a_higher_class_deny_beats_a_lower_class_permit() -> None:
    deny = _rule("1", "2", "f1", "deny", prio="fully_qual")
    permit = _rule("any", "2", "f2", "permit", prio="any_dest_filter")
    decision = _decide([permit, deny], [_entry("f1", dport="80"), _entry("f2", dport="80")])
    assert decision.outcome == "deny"


def test_a_permit_and_a_deny_of_one_priority_class_are_not_guessed() -> None:
    rules = [_rule("1", "2", "f1", "permit"), _rule("1", "2", "f2", "deny,log")]
    decision = _decide(rules, [_entry("f1", dport="80"), _entry("f2", dport="80")])
    assert decision.outcome == "unsure" and "order is not modelled" in (decision.note or "")


def test_a_specific_rule_that_does_not_cover_the_port_does_not_shadow_a_lower_one() -> None:
    rules = [
        _rule("1", "2", "f1", "deny"),
        _rule("any", "2", "f2", "permit", prio="any_dest_filter"),
    ]
    decision = _decide(rules, [_entry("f1", dport="22"), _entry("f2", dport="80")])
    assert decision.outcome == "permit" and decision.rule is not None
    assert decision.rule.filter_id == "f2"


# -- finding 5 and 6: what cannot be judged is unsure, never a permit or a deny ----------------


def test_a_blank_or_unknown_action_is_never_reported_as_a_permit() -> None:
    for action in (None, "", "mystery"):
        blank_implicit = _rule("any", "any", "implicit", action, prio="any_any_any")
        decision = _decide([blank_implicit], [])
        assert decision.outcome == "unsure" and "action" in (decision.note or "")


def test_an_unknown_priority_class_is_unsure() -> None:
    rule = _rule("1", "2", "f1", "permit", prio="brand_new_class")
    decision = _decide([rule, IMPLICIT_DENY], [_entry("f1", dport="80")])
    assert decision.outcome == "unsure" and "brand_new_class" in (decision.note or "")
    assert (
        _decide([_rule("1", "2", "f1", prio=None)], [_entry("f1", dport="80")]).outcome == "unsure"
    )


def test_a_client_source_port_makes_the_rule_unsure_unless_it_names_all_ports() -> None:
    rule = [_rule("1", "2", "f1")]
    narrow = _decide(rule, [_entry("f1", dport="80", sport="1024")])
    assert narrow.outcome == "unsure" and "source port" in (narrow.note or "")
    wide = _decide(rule, [_entry("f1", dport="80", sport="0", sto="65535")])
    assert wide.outcome == "permit"


def test_a_port_name_that_cannot_be_read_is_unsure_not_a_miss() -> None:
    assert _decide([_rule("1", "2", "f1")], [_entry("f1", dport="ssh")]).outcome == "unsure"


def test_an_uncertain_rule_of_a_lower_priority_class_does_not_block_a_sure_one() -> None:
    rules = [
        _rule("1", "2", "f1", "permit"),
        _rule("any", "2", "f2", "permit", prio="any_dest_filter"),
    ]
    filters = [_entry("f1", dport="80"), _entry("f2", dport="80", sport="1024")]
    assert _decide(rules, filters).outcome == "permit"
    # ... but one of a higher class does.
    higher = [
        _rule("1", "2", "f2", "deny", prio="fully_qual"),
        _rule("1", "2", "f1", prio="src_dst_any"),
    ]
    assert _decide(higher, filters).outcome == "unsure"


def test_ports_ranges_protocols_and_unspecified_entries() -> None:
    rules = [_rule("1", "2", "f1")]

    def run(entry: AciFilterEntry, protocol="tcp", port=8443):
        return _decide(rules, [entry], protocol=protocol, port=port).outcome

    assert run(_entry("f1", dport="8000", dto="9000")) == "permit"
    assert run(_entry("f1", dport="https"), port=443) == "permit"
    assert run(_entry("f1", proto=None)) == "permit"  # no protocol = any protocol and port
    assert run(_entry("f1", dport="80")) is None
    assert run(_entry("f1", proto="udp", dport="8443")) is None
    assert run(_entry("f1", ether="arp")) is None
    assert run(_entry("f1")) == "permit"  # tcp, no port = any port
    assert run(_entry("f1", proto="icmp"), protocol="icmp", port=None) == "permit"


def test_the_reverse_leg_and_rules_of_other_scopes_are_ignored() -> None:
    rules = [
        _rule("1", "2", "f1", direction="uni-dir-ignore"),
        AciContractRule(
            scope="9",
            source_pc_tag="1",
            destination_pc_tag="2",
            filter_id="f1",
            action="permit",
            priority="fully_qual",
            state="enabled",
        ),
    ]
    assert _decide(rules, [_entry("f1", dport="80")]).outcome is None


# -- finding 3: a rule that is not enabled is not enforced -------------------------------------


def test_a_disabled_rule_is_ignored_and_a_missing_state_counts_as_enabled() -> None:
    off = _rule("1", "2", "f1", "permit", state="disabled")
    decision = _decide([off, IMPLICIT_DENY], [_entry("f1", dport="80")])
    assert decision.outcome == "deny"  # the disabled permit does not count
    unset = _rule("1", "2", "f1", "permit", state=None)  # type: ignore[arg-type]
    assert _decide([unset, IMPLICIT_DENY], [_entry("f1", dport="80")]).outcome == "permit"


def test_only_disabled_rules_mean_not_enforced_on_the_leaf() -> None:
    off = _rule("1", "2", "f1", "permit", state="disabled")
    decision = _decide([off], [_entry("f1", dport="80")])
    assert decision.outcome is None and decision.only_disabled


# -- tags of EPGs ------------------------------------------------------------------------------


def test_epg_tag_from_the_snapshot_for_application_and_external_epgs() -> None:
    from models.aci_policy import AciExternalEpg, AciPolicyEpg, AciPolicyL3Out
    from services.aci.policy_service import AciPolicySnapshot

    snap = AciPolicySnapshot(
        epgs={"uni/tn-T/ap-A/epg-e": AciPolicyEpg(epg_dn="uni/tn-T/ap-A/epg-e", pc_tag="49154")},
        contracts={},
        l3outs={
            ("T", "o"): AciPolicyL3Out(
                tenant="T",
                name="o",
                external_epgs=(
                    AciExternalEpg(epg_dn="uni/tn-T/out-o/instP-x", name="x", pc_tag="15"),
                ),
            )
        },
    )
    assert epg_tag(snap, "uni/tn-T/ap-A/epg-e") == "49154"
    assert epg_tag(snap, "uni/tn-T/out-o/instP-x") == "15"
    assert epg_tag(snap, "uni/tn-T/ap-A/epg-none") is None and epg_tag(snap, None) is None


# -- reading a leaf ----------------------------------------------------------------------------


class FakeLeaf:
    def __init__(self, scopes: dict[str, str], contracts: AciContracts, fail: bool = False) -> None:
        self.scopes, self.contracts, self.fail = scopes, contracts, fail

    async def get_contracts(self, pod_id: int, node_id: int) -> AciContracts:
        if self.fail:
            raise AciAPIError("down", code="transport")
        return self.contracts

    async def get_vrf_scopes(self, pod_id: int, node_id: int) -> dict[str, str]:
        return self.scopes


def _check(leaf: FakeLeaf, vrf: str | None = "VY-TN/VY-VRF", src=EPG2, dst=VY, port=443):
    return asyncio.run(
        check_leaf(
            leaf,
            AciFlowLeaf(pod_id=1, node_id=101),
            vrf=vrf,
            src_tag=src,
            dst_tag=dst,
            protocol="tcp",
            port=port,
        )
    )


def test_a_leaf_check_names_the_rule_the_entries_and_the_state() -> None:
    leaf = FakeLeaf({"VY-TN/VY-VRF": SCOPE}, asyncio.run(_contracts()))
    result = _check(leaf)
    assert result.outcome == "permit" and result.rule is not None
    assert (result.rule.filter_id, result.rule.state) == ("9", "enabled")
    assert result.entries == ("tcp https",)


def test_the_unfaked_simulated_leaf_is_not_enforced_not_permit() -> None:
    leaf = FakeLeaf({"VY-TN/VY-VRF": SCOPE}, asyncio.run(_contracts(None)))
    result = _check(leaf)
    assert result.outcome == "not_enforced" and "not enabled" in (result.note or "")


def test_a_vrf_that_is_not_on_the_leaf_a_failing_leaf_and_no_matching_rule() -> None:
    contracts = asyncio.run(_contracts())
    assert _check(FakeLeaf({}, contracts)).outcome == "no_vrf_scope"
    assert _check(FakeLeaf({"VY-TN/VY-VRF": SCOPE}, contracts), vrf=None).outcome == "no_vrf_scope"
    assert _check(FakeLeaf({}, contracts, fail=True)).outcome == "unreadable"
    assert _check(FakeLeaf({"VY-TN/VY-VRF": SCOPE}, AciContracts())).outcome == "no_rule"


def test_an_unsure_rule_gives_a_leaf_check_with_the_reason() -> None:
    rules = (_rule("1", "2", "f1", "permit"), _rule("1", "2", "f2", "deny"))
    filters = (_entry("f1", dport="80"), _entry("f2", dport="80"))
    leaf = FakeLeaf({"T/v": SCOPE}, AciContracts(rules=rules, filters=filters))
    result = _check(leaf, vrf="T/v", src="1", dst="2", port=80)
    assert result.outcome == "unsure" and result.rule is None and result.note


# -- finding 4: the unknown-tenant VRF lookup is an exact name match ---------------------------


def test_a_vrf_without_a_known_tenant_matches_only_the_exact_name() -> None:
    contracts = asyncio.run(_contracts())
    nonprod = FakeLeaf({"ACME/nonprod": "99", "ACME/web": SCOPE}, contracts)
    assert _check(nonprod, vrf="?/prod").outcome == "no_vrf_scope"  # "nonprod" is not "prod"
    exact = FakeLeaf({"ACME/nonprod": "99", "ACME/prod": SCOPE}, contracts)
    assert _check(exact, vrf="?/prod").outcome == "permit"
    two = FakeLeaf({"A/prod": SCOPE, "B/prod": "9"}, contracts)
    assert _check(two, vrf="?/prod").outcome == "no_vrf_scope"  # ambiguous: no guess


# -- finding 2: partial answers, skipped leaves ------------------------------------------------


def _verdict(intent: str, leaves=((1, 101),), dest_leaves=((1, 102),)) -> AciFlowVerdict:
    def party(address, node_ids):
        return AciFlowParty(
            address=address,
            how="endpoint",
            epg_dn="uni/tn-T/ap-A/epg-e",
            leaves=tuple(AciFlowLeaf(pod_id=p, node_id=n) for p, n in node_ids),
        )

    return AciFlowVerdict(
        source=party("10.0.0.1", leaves),
        destination=party("10.0.0.2", dest_leaves),
        protocol="tcp",
        port=443,
        verdict=intent,  # type: ignore[arg-type]
        reason="r",
        explanation="e",
    )


def _checks(*outcomes: str) -> list[AciFlowLeafCheck]:
    return [
        AciFlowLeafCheck(pod_id=1, node_id=100 + i, outcome=o)  # type: ignore[arg-type]
        for i, o in enumerate(outcomes)
    ]


@pytest.mark.parametrize(
    "outcomes,skipped,summary",
    [
        (["permit"], 0, "permit"),
        (["permit", "permit"], 0, "permit"),
        (["deny", "deny"], 0, "deny"),
        (["permit", "deny"], 0, "mixed"),
        (["permit", "unreadable"], 0, "partial"),
        (["permit", "no_rule"], 0, "partial"),
        (["deny", "not_enforced"], 0, "partial"),
        (["permit", "unsure"], 0, "partial"),
        (["permit", "no_vrf_scope"], 0, "partial"),
        (["permit", "permit"], 1, "partial"),
        (["redirect"], 0, "redirect"),
        (["unreadable", "no_rule"], 0, "unavailable"),
        (["unsure"], 0, "unavailable"),
    ],
)
def test_the_summary_is_definite_only_when_every_leaf_answered_and_none_was_left_out(
    outcomes: list[str], skipped: int, summary: str
) -> None:
    assert summarize(_checks(*outcomes), skipped) == summary


def test_the_source_leaf_failing_while_the_destination_permits_is_partial_not_permit() -> None:
    out = attach_programmed(_verdict("permitted"), _checks("unreadable", "permit"))
    assert out.programmed_summary == "partial"
    assert "Only some leaves answered" in (out.programmed_note or "")
    assert "enforce what the contracts intend" not in (out.programmed_note or "")


def test_leaves_beyond_the_limit_are_counted_not_silently_dropped() -> None:
    nodes = tuple((1, 100 + i) for i in range(MAX_ZONING_LEAVES + 2))
    kept, skipped = leaves_to_check(_verdict("permitted", leaves=nodes, dest_leaves=nodes[:1]))
    assert [leaf.node_id for leaf in kept] == [100, 101, 102, 103] and skipped == 2
    out = attach_programmed(_verdict("permitted"), _checks("permit", "permit"), skipped)
    assert out.programmed_summary == "partial" and out.programmed_leaves_skipped == 2


@pytest.mark.parametrize(
    "intent,outcomes,summary,fragment",
    [
        ("permitted", ["permit"], "permit", "enforce what the contracts intend"),
        ("not_permitted", ["deny"], "deny", "enforce what the contracts intend"),
        ("permitted", ["deny"], "deny", "Differs"),
        ("not_permitted", ["permit"], "permit", "Differs"),
        ("unknown", ["permit"], "permit", "settle what the intent could not"),
        ("permitted", ["permit", "deny"], "mixed", "disagree"),
        ("permitted", ["redirect"], "redirect", "redirects"),
        ("permitted", ["unreadable", "no_rule"], "unavailable", "No leaf gave an answer"),
    ],
)
def test_the_comparison_with_the_intent(
    intent: str, outcomes: list[str], summary: str, fragment: str
) -> None:
    out = attach_programmed(_verdict(intent), _checks(*outcomes))
    assert out.programmed_summary == summary and fragment in (out.programmed_note or "")
    assert out.verdict == intent  # the intent is never overwritten
