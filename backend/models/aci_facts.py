"""Normalized per-switch facts read from a Cisco ACI fabric (APIC).

Raw APIC payloads stay inside ``services.aci``; steps and tools only see these frozen, whitelisted
shapes. Every field is optional because the APIC blanks, zeroes or omits values freely (and a value
such as ``inherit`` or ``unknown`` means "not set", which the service maps to ``None``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Fact(BaseModel):
    model_config = ConfigDict(frozen=True)


class AciDeviceDetails(_Fact):
    """``topSystem`` + ``fabricNode`` of one switch: identity and state."""

    node_id: int
    pod_id: int | None = None
    name: str | None = None
    role: str | None = None
    model: str | None = None
    vendor: str | None = None
    serial_number: str | None = None
    fabric_state: str | None = None
    system_state: str | None = None
    system_uptime: str | None = None
    system_uptime_seconds: int | None = None
    last_reboot_time: str | None = None
    last_reset_reason: str | None = None
    current_time: str | None = None
    # Fabric-internal addresses: never a management address.
    tep_address: str | None = None
    tep_pool: str | None = None
    fabric_mac: str | None = None
    fabric_id: str | None = None
    fabric_domain: str | None = None
    control_plane_mtu: int | None = None
    # Out-of-band, else in-band management IPv4; ``None`` when the fabric has none configured.
    management_ip: str | None = None
    oob_ip: str | None = None
    inb_ip: str | None = None


class AciSoftware(_Fact):
    """``firmwareRunning`` and ``topSystem.version`` of one switch."""

    software_version: str | None = None
    image_type: str | None = None
    # ``topSystem.version``, as the switch reports it (may differ in spelling from the image).
    system_version: str | None = None


AciHardwareKind = Literal[
    "chassis",
    "supervisor",
    "line_card",
    "fabric_card",
    "system_controller",
    "fan",
    "power_supply",
    "cpu",
    "memory",
]


class AciHardwareItem(_Fact):
    """One piece of equipment (chassis, module, fan, PSU, CPU, memory)."""

    kind: AciHardwareKind
    # Slot of the module (or of the fan tray / PSU); for a CPU or memory the module it sits on.
    slot: int | None = None
    # Number inside the slot: fan number, CPU number, DIMM number.
    index: int | None = None
    model: str | None = None
    serial_number: str | None = None
    revision: str | None = None
    vendor: str | None = None
    description: str | None = None
    state: str | None = None


AciInterfaceKind = Literal["physical", "port_channel", "management", "loopback", "svi"]


class AciInterfaceAddress(_Fact):
    address: str
    type: str | None = None
    vrf: str | None = None


class AciInterface(_Fact):
    """One interface of a switch, from the configuration and the operational objects."""

    name: str
    kind: AciInterfaceKind
    description: str | None = None
    admin_status: str | None = None
    oper_status: str | None = None
    oper_status_reason: str | None = None
    layer: str | None = None
    mode: str | None = None
    mtu: int | None = None
    speed: str | None = None
    oper_speed: str | None = None
    duplex: str | None = None
    mac_address: str | None = None
    # ``leaf`` (host facing) or ``fab`` (fabric facing), from ``l1PhysIf.portT``.
    port_type: str | None = None
    usage: str | None = None
    access_vlan: str | None = None
    native_vlan: str | None = None
    allowed_vlans: str | None = None
    vlan_id: int | None = None
    last_link_change: str | None = None
    ipv4_addresses: tuple[AciInterfaceAddress, ...] = ()
    # The port-channel this physical interface is a member of.
    port_channel: str | None = None
    # For a port-channel: its member interfaces.
    members: tuple[str, ...] = ()


class AciNeighbor(_Fact):
    """One LLDP (or CDP) neighbour learned on a switch port."""

    protocol: Literal["lldp", "cdp"]
    local_port: str | None = None
    remote_name: str | None = None
    remote_port: str | None = None
    remote_port_id: str | None = None
    remote_mgmt_ip: str | None = None
    remote_chassis_id: str | None = None
    remote_model: str | None = None
    remote_software: str | None = None
    description: str | None = None
    capabilities: str | None = None
    ttl: int | None = None


class AciVlan(_Fact):
    """One encapsulation VLAN (``vlanCktEp``) used on a leaf, with its EPG, bridge domain, VRF."""

    vlan_id: int | None = None
    encap: str | None = None
    encap_vlan: int | None = None
    fabric_encap: str | None = None
    name: str | None = None
    epg: str | None = None
    bridge_domain: str | None = None
    vrf: str | None = None
    state: str | None = None


class AciHealth(_Fact):
    """Health scores of a switch (``sys/health``) and its chassis (``sys/ch/health``)."""

    score: int | None = None
    previous_score: int | None = None
    change: int | None = None
    max_severity: str | None = None
    chassis_score: int | None = None
    chassis_previous_score: int | None = None


class AciFault(_Fact):
    code: str | None = None
    severity: str | None = None
    cause: str | None = None
    description: str | None = None
    created: str | None = None
    lifecycle: str | None = None
    type: str | None = None
    subject: str | None = None
    domain: str | None = None
    acknowledged: bool | None = None
    dn: str | None = None


class AciFaults(_Fact):
    """Faults raised on a switch: the total, the count per severity, and the worst ones."""

    total: int = 0
    by_severity: dict[str, int] = {}
    items: tuple[AciFault, ...] = ()
    # ``True`` when ``items`` holds only the first part of the faults.
    truncated: bool = False


class AciNextHop(_Fact):
    address: str | None = None
    interface: str | None = None
    vrf: str | None = None
    preference: int | None = None
    metric: int | None = None


class AciRoute(_Fact):
    vrf: str | None = None
    prefix: str | None = None
    preference: int | None = None
    metric: int | None = None
    next_hops: tuple[AciNextHop, ...] = ()


class AciBgpPeer(_Fact):
    vrf: str | None = None
    address: str | None = None
    asn: str | None = None
    type: str | None = None
    admin_state: str | None = None
    oper_state: str | None = None


class AciAdjacency(_Fact):
    """An IS-IS or OSPF adjacency. The APIC's own non-empty attributes are kept verbatim."""

    protocol: Literal["isis", "ospf"]
    state: str | None = None
    attributes: dict[str, str] = {}


class AciProtocols(_Fact):
    bgp_peers: tuple[AciBgpPeer, ...] = ()
    adjacencies: tuple[AciAdjacency, ...] = ()


class AciEndpoint(_Fact):
    """An endpoint (IP or MAC) the leaf has learned."""

    kind: Literal["ip", "mac"]
    address: str
    interface: str | None = None
    vrf: str | None = None
    encap_vlan: int | None = None
    flags: str | None = None
    pc_tag: str | None = None


class AciVpcInterface(_Fact):
    id: str | None = None
    local_state: str | None = None
    remote_state: str | None = None


class AciVpc(_Fact):
    """The vPC domain of a switch and its vPC interfaces; empty when the switch has none."""

    domain_id: str | None = None
    peer_state: str | None = None
    peer_state_reason: str | None = None
    peer_ip: str | None = None
    role: str | None = None
    virtual_ip: str | None = None
    system_mac: str | None = None
    keepalive_state: str | None = None
    interfaces: tuple[AciVpcInterface, ...] = ()


class AciEpg(_Fact):
    """An EPG deployed on a leaf (``vlanCktEp``): who it is, its tag, encap, bridge domain, VRF."""

    name: str | None = None
    epg_dn: str | None = None
    tenant: str | None = None
    app_profile: str | None = None
    epg: str | None = None
    pc_tag: str | None = None
    encap: str | None = None
    encap_vlan: int | None = None
    fabric_encap: str | None = None
    bridge_domain: str | None = None
    vrf: str | None = None
    state: str | None = None


class AciContractRule(_Fact):
    """One zoning rule the leaf enforces (``actrlRule``): source and destination EPG tags."""

    scope: str | None = None
    source_pc_tag: str | None = None
    destination_pc_tag: str | None = None
    # Names are known for the EPGs deployed on this leaf only.
    source_epg: str | None = None
    destination_epg: str | None = None
    filter_id: str | None = None
    action: str | None = None
    direction: str | None = None
    priority: str | None = None
    state: str | None = None


class AciFilterEntry(_Fact):
    """One entry of a filter the leaf programmed (``actrlEntry``)."""

    filter_id: str | None = None
    ether_type: str | None = None
    protocol: str | None = None
    source_port_from: str | None = None
    source_port_to: str | None = None
    destination_port_from: str | None = None
    destination_port_to: str | None = None
    stateful: str | None = None


class AciContracts(_Fact):
    """The contracts as the leaf enforces them: zoning rules plus their filter entries."""

    rules: tuple[AciContractRule, ...] = ()
    filters: tuple[AciFilterEntry, ...] = ()
