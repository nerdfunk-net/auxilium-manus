"""What a leaf's programmed zoning rules do with a flow: the hardware's second opinion.

The contract objects are intent; the leaf enforces ``actrlRule`` / ``actrlEntry`` rows: a VRF
scope id, a source and a destination class tag (``any`` is a wildcard), a filter, an action and a
**priority class** (``prio``). The leaf validates the rules in the order of their priority class
and the first match decides (Cisco's *Troubleshoot ACI Security Policies*: ``fully_qual(7)`` before
``src_dst_any(9)`` ... ``any_any_filter(17)`` before the implicit deny ``any_any_any(21)``).

This module picks the applying rule that way and says what it does. It does not guess: whenever
the answer depends on something it cannot rank or match, the result is ``unsure``, not a permit
or a deny. That is the case for

* a priority class it does not know (``PRIORITY_RANK`` lists the twelve of the Cisco table),
* an action it does not know,
* a filter entry that names a source port (the client's is not known) or a port name it cannot
  read, and
* a permit and a deny of the very same priority class (the order inside a class is not modelled).

Rules whose ``operSt`` is ``disabled`` are not installed: they are ignored (``not_enforced`` when
nothing else applies). The reverse leg of a bidirectional rule (``direction=uni-dir-ignore``) only
matches return traffic and is skipped. Not modelled: the enforcement direction (ingress or
egress), service graphs, shared-service tags and the order of rules inside one class.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from models.aci_facts import AciContractRule, AciContracts, AciFilterEntry
from models.aci_flow import AciFlowLeaf, AciFlowLeafCheck, AciFlowVerdict, AciZoningRule
from models.aci_policy import AciPolicyFilterEntry
from services.aci.common.exceptions import AciError
from services.aci.connectivity import describe_entry
from services.aci.policy_search import port_number
from services.aci.policy_service import AciPolicySnapshot

WILDCARD = "any"
IMPLICIT_FILTER = "implicit"
REVERSE_LEG = "uni-dir-ignore"
DISABLED = "disabled"
MAX_ZONING_LEAVES = 4
_IP_ETHER_TYPES = {None, "ip", "ipv4", "ipv6"}
_ALL_PORTS = (0, 65535)

# Priority class -> its number in the leaf's own ``show zoning-rule`` (lower is checked first).
# Source: Cisco, "Troubleshoot ACI Security Policies" (doc 218030).
PRIORITY_RANK: dict[str, int] = {
    "fully_qual": 7,
    "src_dst_any": 9,
    "shsrc_any_any_deny": 12,
    "src_any_filter": 13,
    "any_dest_filter": 14,
    "any_dest_any": 16,
    "any_any_filter": 17,
    "grp_src_any_any_deny": 18,
    "grp_any_dest_any_deny": 19,
    "grp_any_any_any_permit": 20,
    "any_any_any": 21,
    "any_vrf_any_deny": 22,
}

ZONING_LIMITS = (
    "The leaf check follows the leaf's priority order but is not a copy of its table: it does not "
    "model the enforcement direction, the order of rules inside one priority class, service graphs "
    "or shared-service tags, and it answers 'unsure' when a rule needs a priority class, action, "
    "port name or client source port it cannot judge. Rules that are not enabled are ignored."
)

Outcome = Literal["permit", "deny", "redirect"]
Decided = Literal["permit", "deny", "redirect", "unsure"]


class LeafRuleReader(Protocol):
    """The two reads of ``AciDetailsService`` this module needs."""

    async def get_contracts(self, pod_id: int, node_id: int) -> AciContracts: ...

    async def get_vrf_scopes(self, pod_id: int, node_id: int) -> dict[str, str]: ...


@dataclass(frozen=True)
class LeafDecision:
    """What ``evaluate_leaf`` found: ``outcome`` is ``None`` when no rule applies."""

    outcome: Decided | None = None
    rule: AciContractRule | None = None
    entries: tuple[AciFilterEntry, ...] = ()
    note: str | None = None
    # Rules matched but every one of them is disabled (not installed on the leaf).
    only_disabled: bool = False


def epg_tag(snapshot: AciPolicySnapshot, epg_dn: str | None) -> str | None:
    """The class tag (``pcTag``) of an application or external EPG, from the policy snapshot."""
    if epg_dn is None:
        return None
    if (epg := snapshot.epgs.get(epg_dn)) is not None:
        return epg.pc_tag
    for out in snapshot.l3outs.values():
        for ext in out.external_epgs:
            if ext.epg_dn == epg_dn:
                return ext.pc_tag
    return None


def policy_entry(entry: AciFilterEntry) -> AciPolicyFilterEntry:
    return AciPolicyFilterEntry(
        ether_type=entry.ether_type,
        protocol=entry.protocol,
        source_port_from=entry.source_port_from,
        source_port_to=entry.source_port_to,
        destination_port_from=entry.destination_port_from,
        destination_port_to=entry.destination_port_to,
        stateful=entry.stateful,
    )


def _range(low: str | None, high: str | None) -> tuple[int, int] | None:
    """A port range as numbers; ``None`` when a value is a name this module cannot read."""
    first = port_number(low)
    last = port_number(high if high is not None else low)
    return (first, last) if first is not None and last is not None else None


def _cover(entry: AciFilterEntry, protocol: str, port: int | None) -> bool | None:
    """Does a filter entry cover the flow? ``None`` when that cannot be told."""
    if entry.ether_type not in _IP_ETHER_TYPES:
        return False
    if entry.protocol not in (None, protocol):
        return False
    if entry.protocol is None:
        return True  # no protocol: any protocol and port
    if port is not None and (
        entry.destination_port_from is not None or entry.destination_port_to is not None
    ):
        destination = _range(entry.destination_port_from, entry.destination_port_to)
        if destination is None:
            return None
        if not destination[0] <= port <= destination[1]:
            return False
    if entry.source_port_from is None and entry.source_port_to is None:
        return True
    source = _range(entry.source_port_from, entry.source_port_to)
    # The client's source port is not known: only a range of all ports is sure to match.
    return True if source == _ALL_PORTS else None


def _combine(values: Sequence[bool | None]) -> bool | None:
    """True when any entry surely covers, None when one might, False otherwise."""
    if any(v is True for v in values):
        return True
    return None if any(v is None for v in values) else False


def _action_outcome(action: str | None) -> Outcome | None:
    """The outcome of an action string; ``None`` for one this module does not know."""
    text = (action or "").lower()
    if "deny" in text or "drop" in text:
        return "deny"
    if "redir" in text:
        return "redirect"
    if "permit" in text:
        return "permit"
    return None


def _tags_match(rule: AciContractRule, src_tag: str, dst_tag: str) -> bool:
    return rule.source_pc_tag in (src_tag, WILDCARD) and rule.destination_pc_tag in (
        dst_tag,
        WILDCARD,
    )


def evaluate_leaf(
    rules: Sequence[AciContractRule],
    filters: Sequence[AciFilterEntry],
    *,
    scope: str,
    src_tag: str,
    dst_tag: str,
    protocol: str,
    port: int | None,
) -> LeafDecision:
    """The rule that decides the flow on one leaf, by priority class (see the module doc)."""
    entries_of: dict[str | None, list[AciFilterEntry]] = {}
    for entry in filters:
        entries_of.setdefault(entry.filter_id, []).append(entry)
    candidates: list[tuple[AciContractRule, bool | None]] = []
    disabled = 0
    for rule in rules:
        if rule.scope != scope or rule.direction == REVERSE_LEG:
            continue
        if not _tags_match(rule, src_tag, dst_tag):
            continue
        if rule.filter_id == IMPLICIT_FILTER:
            covers: bool | None = True
        else:
            covers = _combine(
                [_cover(e, protocol, port) for e in entries_of.get(rule.filter_id, [])]
            )
        if covers is False:
            continue
        if rule.state == DISABLED:
            disabled += 1
            continue
        candidates.append((rule, covers))
    if not candidates:
        return LeafDecision(only_disabled=disabled > 0)

    unknown = sorted(
        {r.priority or "(none)" for r, _ in candidates if r.priority not in PRIORITY_RANK}
    )
    if unknown:
        return LeafDecision(
            outcome="unsure",
            note="A rule applies with a priority class this check does not know: "
            + ", ".join(unknown)
            + ".",
        )

    def rank(rule: AciContractRule) -> int:
        return PRIORITY_RANK[rule.priority or ""]

    sure = [(r, rank(r)) for r, covers in candidates if covers is True]
    best = min((n for _, n in sure), default=None)
    maybe = [r for r, covers in candidates if covers is None and (best is None or rank(r) <= best)]
    if maybe:
        return LeafDecision(
            outcome="unsure",
            note="A rule that depends on the client's source port or on a port name this check "
            "cannot read could apply before the decisive rule.",
        )
    winners = [r for r, n in sure if n == best]
    outcomes: set[Outcome | None] = {_action_outcome(r.action) for r in winners}
    only = next(iter(outcomes)) if len(outcomes) == 1 else None
    if only is None:
        reason = (
            "A rule has an action this check does not know."
            if None in outcomes
            else "A permit and a deny of one priority class apply; their order is not modelled."
        )
        return LeafDecision(outcome="unsure", note=reason)
    winner = sorted(winners, key=lambda r: r.filter_id or "")[0]
    return LeafDecision(
        outcome=only, rule=winner, entries=tuple(entries_of.get(winner.filter_id, []))
    )


def _vrf_scope(scopes: dict[str, str], vrf: str | None) -> str | None:
    """The scope id of ``tenant/vrf`` among a leaf's keys (``?``: any tenant, exact VRF name)."""
    if not vrf or "/" not in vrf:
        return None
    tenant, _, name = vrf.partition("/")
    if tenant != "?":
        return scopes.get(f"{tenant}/{name}")
    matches = {s for key, s in scopes.items() if key.partition("/")[2] == name}
    return next(iter(matches)) if len(matches) == 1 else None


async def check_leaf(
    details: LeafRuleReader,
    leaf: AciFlowLeaf,
    *,
    vrf: str | None,
    src_tag: str,
    dst_tag: str,
    protocol: str,
    port: int | None,
) -> AciFlowLeafCheck:
    """Read one leaf's rules and say what they do with the flow (a failed read is flagged)."""
    pod, node = leaf.pod_id, leaf.node_id
    try:
        contracts = await details.get_contracts(pod, node)
        scopes = await details.get_vrf_scopes(pod, node)
    except AciError:
        return AciFlowLeafCheck(
            pod_id=pod, node_id=node, outcome="unreadable", note="The leaf could not be read."
        )
    scope = _vrf_scope(scopes, vrf)
    if scope is None:
        return AciFlowLeafCheck(
            pod_id=pod,
            node_id=node,
            outcome="no_vrf_scope",
            note="The VRF is not deployed on this leaf.",
        )
    decision = evaluate_leaf(
        contracts.rules,
        contracts.filters,
        scope=scope,
        src_tag=src_tag,
        dst_tag=dst_tag,
        protocol=protocol,
        port=port,
    )
    if decision.outcome is None:
        if decision.only_disabled:
            return AciFlowLeafCheck(
                pod_id=pod,
                node_id=node,
                outcome="not_enforced",
                note="Matching rules exist but are not enabled on this leaf, so the hardware does "
                "not enforce them (a simulated switch reports every rule this way).",
            )
        return AciFlowLeafCheck(
            pod_id=pod, node_id=node, outcome="no_rule", note="No zoning rule matched."
        )
    rule = decision.rule
    return AciFlowLeafCheck(
        pod_id=pod,
        node_id=node,
        outcome=decision.outcome,
        note=decision.note,
        rule=None
        if rule is None
        else AciZoningRule(
            scope=rule.scope,
            source_pc_tag=rule.source_pc_tag,
            destination_pc_tag=rule.destination_pc_tag,
            filter_id=rule.filter_id,
            action=rule.action,
            direction=rule.direction,
            priority=rule.priority,
            state=rule.state,
        ),
        entries=tuple(dict.fromkeys(describe_entry(policy_entry(e)) for e in decision.entries)),
    )


ANSWERS = ("permit", "deny", "redirect")


def summarize(
    checks: Sequence[AciFlowLeafCheck], skipped: int = 0
) -> Literal["permit", "deny", "redirect", "mixed", "partial", "unavailable"]:
    """One word for all the leaves.

    ``permit`` / ``deny`` / ``redirect`` only when every checked leaf gave that answer and none
    was left out; ``mixed`` when the answers differ; ``partial`` when some leaves answered and
    others did not (unreadable, no rule, not enforced, unsure, VRF missing) or were not read;
    ``unavailable`` when none answered.
    """
    answers = {c.outcome for c in checks if c.outcome in ANSWERS}
    if not answers:
        return "unavailable"
    if len(answers) > 1:
        return "mixed"
    if skipped or any(c.outcome not in ANSWERS for c in checks):
        return "partial"
    return next(iter(answers))  # type: ignore[return-value]


# Verdicts whose hosts or VRFs the leaf check cannot place: there is nothing to look up.
SKIP_REASONS = frozenset(
    {
        "source_not_found",
        "destination_not_found",
        "esg_not_evaluated",
        "different_vrf",
        "not_resolved",
    }
)


def leaves_to_check(verdict: AciFlowVerdict) -> tuple[list[AciFlowLeaf], int]:
    """The leaves of both hosts (the rule sits on the source's or the destination's, by VRF),
    at most ``MAX_ZONING_LEAVES`` of them, and how many more there were."""
    both = sorted(
        {
            (leaf.pod_id, leaf.node_id)
            for party in (verdict.source, verdict.destination)
            for leaf in party.leaves
        }
    )
    kept = [AciFlowLeaf(pod_id=p, node_id=n) for p, n in both[:MAX_ZONING_LEAVES]]
    return kept, max(0, len(both) - MAX_ZONING_LEAVES)


def _compare(intent: str, summary: str, checks: Sequence[AciFlowLeafCheck], skipped: int) -> str:
    answers = sorted({c.outcome for c in checks if c.outcome in ANSWERS})
    note = {
        ("permitted", "permit"): "The leaves enforce what the contracts intend: permit.",
        ("not_permitted", "deny"): "The leaves enforce what the contracts intend: deny.",
        ("permitted", "deny"): (
            "Differs: the contracts permit it, but the leaves enforce a deny. The policy may not "
            "be programmed yet, or a rule of a higher priority class denies it. The leaf rule "
            "below is what is enforced."
        ),
        ("not_permitted", "permit"): (
            "Differs: no contract was found, yet the leaves permit it. A vzAny, preferred-group or "
            "other rule not modelled in the intent is at work. The leaf rule below is what is "
            "enforced."
        ),
        ("unknown", "permit"): "The leaf rules settle what the intent could not: they permit it.",
        ("unknown", "deny"): "The leaf rules settle what the intent could not: they deny it.",
    }.get((intent, summary))
    if summary == "redirect":
        note = "A leaf redirects this flow (service graph or policy-based redirect): not evaluated."
    elif summary == "mixed":
        note = "The leaves disagree: see each leaf; the flow may depend on where it enters."
    elif summary == "partial":
        missing = sum(1 for c in checks if c.outcome not in ANSWERS) + skipped
        note = (
            f"Only some leaves answered ({missing} did not or were not read); the answered ones "
            f"say {', '.join(answers)}, the others may differ. The contract intent was {intent}."
        )
    elif summary == "unavailable":
        note = "No leaf gave an answer (see each leaf): the hardware's decision is unknown."
    note = note or f"The leaves report {summary}; the contract intent was {intent}."
    states = {c.rule.state for c in checks if c.rule is not None and c.rule.state}
    if states - {"enabled"}:
        note += " A rule state other than enabled was reported."
    return note


def attach_programmed(
    verdict: AciFlowVerdict, checks: Sequence[AciFlowLeafCheck], skipped: int = 0
) -> AciFlowVerdict:
    """The verdict with the leaves' answers, their summary and how it compares with the intent."""
    summary = summarize(checks, skipped)
    return verdict.model_copy(
        update={
            "programmed": tuple(checks),
            "programmed_summary": summary,
            "programmed_note": _compare(verdict.verdict, summary, checks, skipped),
            "programmed_leaves_skipped": skipped,
        }
    )
