"""Fabric policy read from the APIC: EPGs, contracts, subjects, filters (frozen, whitelisted).

Raw APIC payloads stay inside ``services.aci``. A value the APIC writes as ``unspecified`` or
leaves blank is ``None``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Policy(BaseModel):
    model_config = ConfigDict(frozen=True)


class AciPolicyFilterEntry(_Policy):
    name: str | None = None
    ether_type: str | None = None
    protocol: str | None = None
    source_port_from: str | None = None
    source_port_to: str | None = None
    destination_port_from: str | None = None
    destination_port_to: str | None = None
    stateful: str | None = None
    apply_to_fragments: str | None = None
    tcp_flags: str | None = None


class AciPolicyFilter(_Policy):
    name: str
    tenant: str
    entries: tuple[AciPolicyFilterEntry, ...] = ()


class AciPolicySubject(_Policy):
    name: str
    filters: tuple[AciPolicyFilter, ...] = ()


class AciPolicyContract(_Policy):
    """A contract with its subjects and filters and the EPGs on both sides (fabric-wide)."""

    tenant: str
    name: str
    scope: str | None = None
    priority: str | None = None
    subjects: tuple[AciPolicySubject, ...] = ()
    provider_epgs: tuple[str, ...] = ()
    consumer_epgs: tuple[str, ...] = ()


class AciPolicyEpg(_Policy):
    """An application EPG with the contracts it provides and consumes (``tenant/name``)."""

    epg_dn: str
    tenant: str | None = None
    app_profile: str | None = None
    epg: str | None = None
    pc_tag: str | None = None
    bridge_domain: str | None = None
    provided: tuple[str, ...] = ()
    consumed: tuple[str, ...] = ()


class AciVrfPolicy(_Policy):
    """How a VRF treats contracts: enforcement, preferred group and the ``vzAny`` contracts."""

    tenant: str
    name: str
    enforced: bool = True
    preferred_group: bool = False
    any_provided: tuple[str, ...] = ()
    any_consumed: tuple[str, ...] = ()


class AciEpgFlags(_Policy):
    """Per-EPG switches that change the contract result: preferred group, isolation, taboo."""

    epg_dn: str
    preferred_group: bool = False
    # Intra-EPG isolation (``pcEnfPref=enforced``): members of the EPG cannot talk to each other.
    isolated: bool = False
    taboo: tuple[str, ...] = ()


class AciExternalSubnet(_Policy):
    """A subnet of an external EPG; ``scope`` holds the APIC's flags (``import-security``, ...)."""

    ip: str
    scope: tuple[str, ...] = ()
    aggregate: tuple[str, ...] = ()


class AciExternalEpg(_Policy):
    """An external EPG (``l3extInstP``) of an L3Out with its subnets and contracts."""

    epg_dn: str
    name: str
    pc_tag: str | None = None
    subnets: tuple[AciExternalSubnet, ...] = ()
    provided: tuple[str, ...] = ()
    consumed: tuple[str, ...] = ()


class AciL3OutNode(_Policy):
    pod_id: int
    node_id: int
    router_id: str | None = None


class AciL3OutInterface(_Policy):
    """A routed port, sub-interface or SVI of an L3Out (a vPC path names two nodes)."""

    pod_id: int
    node_ids: tuple[int, ...]
    interface: str
    address: str | None = None
    type: str | None = None
    encap: str | None = None
    mtu: str | None = None


class AciPolicyL3Out(_Policy):
    tenant: str
    name: str
    vrf: str | None = None
    protocols: tuple[str, ...] = ()
    nodes: tuple[AciL3OutNode, ...] = ()
    interfaces: tuple[AciL3OutInterface, ...] = ()
    external_epgs: tuple[AciExternalEpg, ...] = ()
