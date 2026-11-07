"""Result of a "can A reach B on this port" assessment from the fabric's contract policy.

This is a reading of the policy (intent), not a packet trace: ``verdict`` is ``permitted``,
``not_permitted`` or ``unknown`` (the APIC data does not decide it, ``reason`` says why).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Flow(BaseModel):
    model_config = ConfigDict(frozen=True)


class AciFlowLeaf(_Flow):
    pod_id: int
    node_id: int


class AciZoningRule(_Flow):
    """The zoning rule (``actrlRule``) a leaf applies to the flow: the most specific match."""

    scope: str | None = None
    source_pc_tag: str | None = None
    destination_pc_tag: str | None = None
    filter_id: str | None = None
    action: str | None = None
    direction: str | None = None
    priority: str | None = None
    state: str | None = None


class AciFlowLeafCheck(_Flow):
    """What one leaf's programmed zoning rules do with the flow: the hardware's own answer."""

    pod_id: int
    node_id: int
    # ``permit`` / ``deny`` / ``redirect`` from the winning rule. No answer: ``no_rule`` (nothing
    # matched), ``not_enforced`` (matching rules exist but are not enabled on the leaf), ``unsure``
    # (a rule applies that this check cannot rank or match: an unknown priority class, action,
    # port name or a client source port, or a permit and a deny of one priority),
    # ``no_vrf_scope`` (the VRF is not deployed on this leaf) or ``unreadable`` (the read failed).
    outcome: Literal[
        "permit",
        "deny",
        "redirect",
        "no_rule",
        "not_enforced",
        "unsure",
        "no_vrf_scope",
        "unreadable",
    ]
    rule: AciZoningRule | None = None
    # The protocol and ports of the winning rule's filter, so the answer shows what it covers.
    entries: tuple[str, ...] = ()
    note: str | None = None


class AciFlowParty(_Flow):
    """One side of the flow, as the fabric sees it."""

    address: str
    # ``endpoint`` (learned host), ``external_subnet`` (matched an L3Out external EPG subnet) or
    # ``unknown`` (neither: the fabric has not learned it and no external subnet covers it).
    how: Literal["endpoint", "external_subnet", "unknown"] = "unknown"
    epg_dn: str | None = None
    epg_path: str | None = None
    vrf: str | None = None
    esg: str | None = None
    # The leaves this host is attached to; where its zoning rules can be read.
    leaves: tuple[AciFlowLeaf, ...] = ()


class AciFlowContract(_Flow):
    tenant: str
    name: str
    scope: str | None = None
    # Filter entries that cover the asked protocol and port (empty when none does).
    matching_entries: tuple[str, ...] = ()
    # Every protocol / port the contract has, so a wrong-port answer shows what is allowed.
    entries: tuple[str, ...] = ()


class AciFlowVerdict(_Flow):
    source: AciFlowParty
    destination: AciFlowParty
    protocol: str
    port: int | None = None
    verdict: Literal["permitted", "not_permitted", "unknown"]
    reason: str
    explanation: str
    contracts: tuple[AciFlowContract, ...] = ()
    notes: tuple[str, ...] = ()
    # Only with ``verify_on_leaf``: the leaves' programmed zoning rules, a summary and how it
    # compares with the contract intent above.
    programmed: tuple[AciFlowLeafCheck, ...] = ()
    # ``partial``: some leaves answered, others did not (or were not read); ``mixed``: they differ.
    programmed_summary: (
        Literal["permit", "deny", "redirect", "mixed", "partial", "unavailable"] | None
    ) = None
    programmed_note: str | None = None
    # Leaves of the two hosts beyond the limit that were not read.
    programmed_leaves_skipped: int = 0
