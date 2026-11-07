"""Per-switch detail facts from a Cisco ACI fabric (read-only).

Every fact is a few ``GET /api/node/class/topology/pod-<p>/node-<n>/<Class>.json`` reads (verified
on the DevNet always-on APIC, 6.1(4h)) plus, for health, ``GET /api/mo/...``. Classes are
constants and pod/node are validated whole numbers, so nothing a user types reaches a URL.

- ``device`` / ``software``: ``topSystem`` (object ``sys``), ``fabricNode``, ``firmwareRunning``
- ``hardware``: ``eqptCh``, ``eqptSupC``, ``eqptLC``, ``eqptFC``, ``eqptSysC``, ``eqptFan``,
  ``eqptPsu``, ``eqptCPU``, ``eqptDimm``
- ``interfaces``: ``l1PhysIf`` + ``ethpmPhysIf``, ``pcAggrIf`` + ``pcRsMbrIfs``, ``mgmtMgmtIf``,
  ``l3LbRtdIf``, ``sviIf``, ``ipv4Addr``
- ``neighbors``: ``lldpAdjEp``, ``cdpAdjEp``;  ``vlans``: ``vlanCktEp``, ``l2BD``, ``l3Ctx``
- ``health``: ``sys/health``, ``sys/ch/health``;  ``faults``: ``faultInst``
- ``routes``: ``ipv4Route``, ``ipv4Nexthop``;  ``protocols``: ``bgpPeer``, ``bgpPeerEntry``,
  ``isisAdjEp``, ``ospfAdjEp``;  ``endpoints``: ``epmIpEp``, ``epmMacEp``
- ``vpc``: ``vpcDom``, ``vpcIf``
- ``epgs``: ``vlanCktEp`` (+ ``l2BD``, ``l3Ctx``);  ``contracts``: ``actrlRule``, ``actrlEntry``
  (the zoning rules the leaf enforces; not verifiable on the sandbox, which has no rules)

A class that is only *optional* for a switch (a spine has no ``sviIf``, a fabric without vPC has no
``vpcDom``) is skipped when the APIC answers 400 "unresolved class"; every other error fails the
fact. A fact never returns a silently truncated list: the row limits below fail it instead.
Values the APIC uses for "not set" (``inherit``, ``unknown``, ``0.0.0.0``, all-zero MACs) become
``None``. CDP neighbours, BGP session state and IS-IS/OSPF adjacencies could not be verified on the
sandbox (it has no rows); they are read best-effort from the documented attribute names.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable
from typing import Any, Protocol

from models.aci_facts import (
    AciAdjacency,
    AciBgpPeer,
    AciContractRule,
    AciContracts,
    AciDeviceDetails,
    AciEndpoint,
    AciEpg,
    AciFault,
    AciFaults,
    AciFilterEntry,
    AciHardwareItem,
    AciHardwareKind,
    AciHealth,
    AciInterface,
    AciInterfaceAddress,
    AciNeighbor,
    AciNextHop,
    AciProtocols,
    AciRoute,
    AciSoftware,
    AciVlan,
    AciVpc,
    AciVpcInterface,
)
from services.aci.common.coerce import integer, text, usable_ipv4
from services.aci.common.exceptions import AciNotFoundError, AciValidationError
from services.aci.credentials import AciCredentials

# Row limits (a fact fails with ``too_many_objects`` instead of being truncated). They bound the
# memory and APIC load of one read, not the size of the stored run result: the persisted copy
# caps each fact on its own (``services/execution/output_cap.py``), so a big fact never hides a
# small one.
MAX_INTERFACE_ROWS = 5_000
MAX_ADDRESS_ROWS = 20_000
MAX_VLAN_ROWS = 5_000
MAX_ROUTE_ROWS = 20_000
MAX_NEXTHOP_ROWS = 100_000
MAX_ENDPOINT_ROWS = 10_000
MAX_FAULT_ROWS = 10_000
MAX_RULE_ROWS = 20_000
MAX_FILTER_ROWS = 20_000
MAX_SMALL_ROWS = 5_000
FAULT_ITEM_LIMIT = 50
FAULT_DESCRIPTION_CHARS = 300

# Values the APIC writes when an attribute is not set.
_UNSET = frozenset({"", "inherit", "unknown", "unspecified", "not-applicable"})
_SEVERITY_RANK = {"critical": 0, "major": 1, "minor": 2, "warning": 3, "info": 4, "cleared": 5}
_INTERFACE_KIND_RANK: dict[str, int] = {
    "physical": 0,
    "port_channel": 1,
    "management": 2,
    "loopback": 3,
    "svi": 4,
}
_HARDWARE_KIND_RANK: dict[str, int] = {
    kind: rank
    for rank, kind in enumerate(
        (
            "chassis",
            "system_controller",
            "supervisor",
            "line_card",
            "fabric_card",
            "power_supply",
            "fan",
            "cpu",
            "memory",
        )
    )
}

_UPTIME = re.compile(r"(\d+):(\d{1,2}):(\d{1,2}):(\d{1,2})(?:\.\d+)?")
_MAC = re.compile(r"[0-9A-F]{2}(?::[0-9A-F]{2}){5}")
_SLOT = re.compile(r"/[a-z]*slot-(\d+)")
_INDEX = re.compile(r"/(?:fan|cpu|dimm)-(\d+)$")
_BRACKET_IF = re.compile(r"/if-\[([^\]]+)\]")
_PHYS_IF = re.compile(r"/phys-\[([^\]]+)\]")
_AGGR = re.compile(r"/aggr-\[([^\]]+)\]")
_VRF_DOM = re.compile(r"/dom-([^/]+)/")
_ROUTE_PREFIX = re.compile(r"/rt-\[([^\]]+)\]")
_CTX = re.compile(r"/ctx-\[([^\]]+)\]")
_BD = re.compile(r"/bd-\[([^\]]+)\]")
_ENCAP_VLAN = re.compile(r"vlan-(\d+)$")
_DN_VLAN = re.compile(r"/vlan-\[vlan-(\d+)\]")
_NATURAL = re.compile(r"(\d+)")
_EPG_DN = re.compile(r"^uni/tn-([^/]+)(?:/ap-([^/]+)/epg-([^/]+))?")
_RULE_DN = re.compile(r"/scope-(\d+)/rule-\d+-s-(\d+)-d-(\d+)-f-(\w+)$")
_FILTER_DN = re.compile(r"/flt-(\w+)/")


class AciNodeClient(Protocol):
    async def query_node_class(
        self,
        credentials: AciCredentials,
        pod_id: int,
        node_id: int,
        class_name: str,
        *,
        query_filter: str | None = None,
        max_objects: int = ...,
    ) -> list[dict[str, Any]]: ...

    async def get_node_mo(
        self,
        credentials: AciCredentials,
        pod_id: int,
        node_id: int,
        relative_dn: str,
        class_name: str,
    ) -> dict[str, Any] | None: ...


# --- small parsing helpers ------------------------------------------------------------------------


def parse_uptime_seconds(value: Any) -> int | None:
    """``topSystem.systemUpTime`` (``dd:hh:mm:ss.mmm``) in seconds, or ``None``."""
    match = _UPTIME.fullmatch(text(value) or "")
    if match is None:
        return None
    days, hours, minutes, seconds = (int(part) for part in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def _known(value: Any) -> str | None:
    """Text, or ``None`` for blank and for the APIC's "not set" words."""
    result = text(value)
    return None if result is None or result.lower() in _UNSET else result


def _mac(value: Any) -> str | None:
    result = (text(value) or "").upper()
    if _MAC.fullmatch(result) is None or result == "00:00:00:00:00:00":
        return None
    return result


def _flag(value: Any) -> bool | None:
    result = (text(value) or "").lower()
    return {"yes": True, "no": False, "true": True, "false": False}.get(result)


def _dn(row: dict[str, Any]) -> str:
    return text(row.get("dn")) or ""


def _first(pattern: re.Pattern[str], value: str) -> str | None:
    match = pattern.search(value)
    return match.group(1) if match else None


def _natural_key(name: str) -> list[Any]:
    return [int(part) if part.isdigit() else part for part in _NATURAL.split(name)]


_UNRESOLVED_CLASS = re.compile(r"unresolved class", re.IGNORECASE)


async def _optional(fetch: Awaitable[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Rows of a class this switch (or APIC release) may not have: "unresolved class" is empty."""
    try:
        return await fetch
    except AciValidationError as exc:
        # Only the APIC's "unresolved class" answer means "this switch has no such class": any
        # other 400 (a rejected query, a node that is not ready) must fail the fact.
        if exc.http_status == 400 and _UNRESOLVED_CLASS.search(str(exc)):
            return []
        raise


class AciDetailsService:
    """Read-only per-switch facts for one APIC source (credentials already resolved)."""

    def __init__(self, client: AciNodeClient, credentials: AciCredentials) -> None:
        self._client = client
        self._credentials = credentials

    # --- plumbing --------------------------------------------------------------------------------

    def _rows(
        self,
        pod_id: int,
        node_id: int,
        class_name: str,
        *,
        max_objects: int = MAX_SMALL_ROWS,
        query_filter: str | None = None,
    ) -> Awaitable[list[dict[str, Any]]]:
        return self._client.query_node_class(
            self._credentials,
            pod_id,
            node_id,
            class_name,
            query_filter=query_filter,
            max_objects=max_objects,
        )

    # --- device and software ---------------------------------------------------------------------

    async def get_device_and_software(
        self, pod_id: int, node_id: int
    ) -> tuple[AciDeviceDetails, AciSoftware]:
        """One set of reads serves both the ``device`` and the ``software`` facts."""
        # ``fabricNode`` is the switch node itself (relative dn ""), not an object below it.
        system, node_object, firmware = await asyncio.gather(
            self._client.get_node_mo(self._credentials, pod_id, node_id, "sys", "topSystem"),
            self._client.get_node_mo(self._credentials, pod_id, node_id, "", "fabricNode"),
            self._rows(pod_id, node_id, "firmwareRunning"),
        )
        if system is None:
            raise AciNotFoundError(f"APIC has no switch node {node_id} in pod {pod_id}")
        node = node_object or {}
        oob_ip = usable_ipv4(system.get("oobMgmtAddr"))
        inb_ip = usable_ipv4(system.get("inbMgmtAddr"))
        uptime = text(system.get("systemUpTime"))
        details = AciDeviceDetails(
            node_id=node_id,
            pod_id=integer(system.get("podId")) or pod_id,
            name=text(system.get("name")) or text(node.get("name")),
            role=text(system.get("role")) or text(node.get("role")),
            model=text(node.get("model")),
            vendor=text(node.get("vendor")),
            serial_number=text(system.get("serial")) or text(node.get("serial")),
            fabric_state=text(node.get("fabricSt")),
            system_state=text(system.get("state")),
            system_uptime=uptime,
            system_uptime_seconds=parse_uptime_seconds(uptime),
            last_reboot_time=text(system.get("lastRebootTime")),
            last_reset_reason=_known(system.get("lastResetReason")),
            current_time=text(system.get("currentTime")),
            tep_address=text(system.get("address")) or text(node.get("address")),
            tep_pool=text(system.get("tepPool")),
            fabric_mac=_mac(system.get("fabricMAC")),
            fabric_id=text(system.get("fabricId")),
            fabric_domain=text(system.get("fabricDomain")),
            control_plane_mtu=integer(system.get("controlPlaneMTU")),
            management_ip=oob_ip or inb_ip,
            oob_ip=oob_ip,
            inb_ip=inb_ip,
        )
        # A node can report several images (supervisor, module, switch): the switch image is the
        # running version; without one the system version is used.
        image = next((row for row in firmware if text(row.get("type")) == "switch"), {})
        software = AciSoftware(
            software_version=text(image.get("version")) or text(system.get("version")),
            image_type=text(image.get("type")),
            system_version=text(system.get("version")),
        )
        return details, software

    # --- hardware --------------------------------------------------------------------------------

    async def get_hardware(self, pod_id: int, node_id: int) -> tuple[AciHardwareItem, ...]:
        classes: tuple[tuple[str, AciHardwareKind, bool], ...] = (
            ("eqptCh", "chassis", True),
            ("eqptSysC", "system_controller", False),
            ("eqptSupC", "supervisor", False),
            ("eqptLC", "line_card", False),
            ("eqptFC", "fabric_card", False),
            ("eqptPsu", "power_supply", False),
            ("eqptFan", "fan", False),
            ("eqptCPU", "cpu", False),
            ("eqptDimm", "memory", False),
        )
        fetched = await asyncio.gather(
            *[
                self._rows(pod_id, node_id, cls)
                if required
                else _optional(self._rows(pod_id, node_id, cls))
                for cls, _kind, required in classes
            ]
        )
        items: list[AciHardwareItem] = []
        for (_cls, kind, _required), rows in zip(classes, fetched, strict=True):
            for row in rows:
                dn = _dn(row)
                items.append(
                    AciHardwareItem(
                        kind=kind,
                        slot=integer(_first(_SLOT, dn)),
                        index=integer(_first(_INDEX, dn)),
                        model=text(row.get("model")),
                        serial_number=text(row.get("ser")),
                        revision=text(row.get("rev")),
                        vendor=text(row.get("vendor")),
                        description=text(row.get("descr")),
                        state=text(row.get("operSt")),
                    )
                )
        return tuple(
            sorted(
                items,
                key=lambda i: (_HARDWARE_KIND_RANK[i.kind], i.slot or 0, i.index or 0),
            )
        )

    # --- interfaces ------------------------------------------------------------------------------

    async def get_interfaces(self, pod_id: int, node_id: int) -> tuple[AciInterface, ...]:
        (
            physical,
            operational,
            port_channels,
            members,
            management,
            loopbacks,
            svis,
            addresses,
        ) = await asyncio.gather(
            self._rows(pod_id, node_id, "l1PhysIf", max_objects=MAX_INTERFACE_ROWS),
            _optional(self._rows(pod_id, node_id, "ethpmPhysIf", max_objects=MAX_INTERFACE_ROWS)),
            _optional(self._rows(pod_id, node_id, "pcAggrIf")),
            _optional(self._rows(pod_id, node_id, "pcRsMbrIfs", max_objects=MAX_INTERFACE_ROWS)),
            _optional(self._rows(pod_id, node_id, "mgmtMgmtIf")),
            _optional(self._rows(pod_id, node_id, "l3LbRtdIf")),
            _optional(self._rows(pod_id, node_id, "sviIf")),
            _optional(self._rows(pod_id, node_id, "ipv4Addr", max_objects=MAX_ADDRESS_ROWS)),
        )

        operational_by_name = {
            name: row for row in operational if (name := _first(_PHYS_IF, _dn(row))) is not None
        }
        members_by_channel: dict[str, list[str]] = {}
        channel_of: dict[str, str] = {}
        for row in members:
            channel = _first(_AGGR, _dn(row))
            member = _first(_PHYS_IF, text(row.get("tDn")) or "")
            if channel and member:
                members_by_channel.setdefault(channel, []).append(member)
                channel_of[member] = channel
        addresses_by_name = _addresses_by_interface(addresses)

        interfaces: list[AciInterface] = []
        for row in physical:
            name = text(row.get("id"))
            if name is None:
                continue
            oper = operational_by_name.get(name, {})
            interfaces.append(
                AciInterface(
                    name=name,
                    kind="physical",
                    description=text(row.get("descr")),
                    admin_status=text(row.get("adminSt")),
                    oper_status=text(oper.get("operSt")),
                    oper_status_reason=text(oper.get("operStQual")),
                    layer=text(row.get("layer")),
                    mode=text(row.get("mode")),
                    mtu=integer(row.get("mtu")),
                    speed=_known(row.get("speed")),
                    oper_speed=_known(oper.get("operSpeed")),
                    duplex=_known(oper.get("operDuplex")) or _known(row.get("duplex")),
                    mac_address=_mac(oper.get("backplaneMac")),
                    port_type=text(row.get("portT")),
                    usage=text(row.get("usage")),
                    access_vlan=_known(oper.get("accessVlan")),
                    native_vlan=_known(oper.get("nativeVlan")),
                    allowed_vlans=_known(oper.get("allowedVlans") or oper.get("operVlans")),
                    last_link_change=_known(oper.get("lastLinkStChg")),
                    ipv4_addresses=tuple(addresses_by_name.get(name, ())),
                    port_channel=channel_of.get(name),
                )
            )
        for row in port_channels:
            name = text(row.get("id"))
            if name is None:
                continue
            interfaces.append(
                AciInterface(
                    name=name,
                    kind="port_channel",
                    admin_status=text(row.get("adminSt")),
                    oper_status=text(row.get("operSt")),
                    layer=text(row.get("layer")),
                    mode=text(row.get("mode")),
                    mtu=integer(row.get("mtu")),
                    ipv4_addresses=tuple(addresses_by_name.get(name, ())),
                    members=tuple(sorted(members_by_channel.get(name, ()), key=_natural_key)),
                )
            )
        for row in management:
            name = text(row.get("id"))
            if name is None:
                continue
            interfaces.append(
                AciInterface(
                    name=name,
                    kind="management",
                    admin_status=text(row.get("adminSt")),
                    mtu=integer(row.get("mtu")),
                    speed=_known(row.get("speed")),
                    ipv4_addresses=tuple(addresses_by_name.get(name, ())),
                )
            )
        for row in loopbacks:
            name = text(row.get("id"))
            if name is None:
                continue
            interfaces.append(
                AciInterface(
                    name=name,
                    kind="loopback",
                    admin_status=text(row.get("adminSt")),
                    mtu=integer(row.get("mtu")),
                    ipv4_addresses=tuple(addresses_by_name.get(name, ())),
                )
            )
        for row in svis:
            name = text(row.get("id"))
            if name is None:
                continue
            interfaces.append(
                AciInterface(
                    name=name,
                    kind="svi",
                    admin_status=text(row.get("adminSt")),
                    oper_status=text(row.get("operSt")),
                    mtu=integer(row.get("mtu")),
                    mac_address=_mac(row.get("mac")),
                    vlan_id=integer(row.get("vlanId")),
                    ipv4_addresses=tuple(addresses_by_name.get(name, ())),
                )
            )
        return tuple(
            sorted(interfaces, key=lambda i: (_INTERFACE_KIND_RANK[i.kind], _natural_key(i.name)))
        )

    # --- neighbours ------------------------------------------------------------------------------

    async def get_neighbors(self, pod_id: int, node_id: int) -> tuple[AciNeighbor, ...]:
        lldp, cdp = await asyncio.gather(
            _optional(self._rows(pod_id, node_id, "lldpAdjEp")),
            _optional(self._rows(pod_id, node_id, "cdpAdjEp")),
        )
        neighbours: list[AciNeighbor] = []
        for row in lldp:
            neighbours.append(
                AciNeighbor(
                    protocol="lldp",
                    local_port=_first(_BRACKET_IF, _dn(row)),
                    remote_name=text(row.get("sysName")) or text(row.get("name")),
                    remote_port=text(row.get("portDesc")),
                    remote_port_id=text(row.get("portIdV")),
                    remote_mgmt_ip=usable_ipv4(row.get("mgmtIp")),
                    remote_chassis_id=text(row.get("chassisIdV")),
                    remote_model=text(row.get("modelNumber")),
                    remote_software=text(row.get("swVersion")),
                    description=text(row.get("sysDesc")),
                    capabilities=text(row.get("capability")),
                    ttl=integer(row.get("ttl")),
                )
            )
        for row in cdp:
            # Best effort: no CDP neighbour exists on the sandbox to check these names against.
            neighbours.append(
                AciNeighbor(
                    protocol="cdp",
                    local_port=_first(_BRACKET_IF, _dn(row)),
                    remote_name=text(row.get("devId")) or text(row.get("sysName")),
                    remote_port=text(row.get("portId")),
                    remote_mgmt_ip=usable_ipv4(row.get("mgmtIp")),
                    remote_model=text(row.get("platId")),
                    remote_software=text(row.get("ver")),
                    ttl=integer(row.get("ttl")),
                )
            )
        return tuple(
            sorted(neighbours, key=lambda n: (_natural_key(n.local_port or ""), n.protocol))
        )

    # --- vlans -----------------------------------------------------------------------------------

    async def get_vlans(self, pod_id: int, node_id: int) -> tuple[AciVlan, ...]:
        circuits, domains, contexts = await asyncio.gather(
            self._rows(pod_id, node_id, "vlanCktEp", max_objects=MAX_VLAN_ROWS),
            _optional(self._rows(pod_id, node_id, "l2BD")),
            _optional(self._rows(pod_id, node_id, "l3Ctx")),
        )
        bridge_domains = _names_by_dn_id(domains, _BD)
        vrfs = _names_by_dn_id(contexts, _CTX)
        vlans = []
        for row in circuits:
            dn = _dn(row)
            encap = text(row.get("encap"))
            match = _ENCAP_VLAN.fullmatch(encap or "")
            vlans.append(
                AciVlan(
                    vlan_id=integer(row.get("id")),
                    encap=encap,
                    encap_vlan=int(match.group(1)) if match else None,
                    fabric_encap=text(row.get("fabEncap")),
                    name=text(row.get("name")),
                    epg=text(row.get("epgDn")),
                    bridge_domain=bridge_domains.get(_first(_BD, dn) or ""),
                    vrf=vrfs.get(_first(_CTX, dn) or ""),
                    state=text(row.get("operSt")),
                )
            )
        return tuple(sorted(vlans, key=lambda v: (v.vlan_id is None, v.vlan_id or 0)))

    # --- EPGs and contracts ----------------------------------------------------------------------

    async def get_epgs(self, pod_id: int, node_id: int) -> tuple[AciEpg, ...]:
        """The EPGs deployed on this leaf, one row per encapsulation (``vlanCktEp``)."""
        circuits, domains, contexts = await asyncio.gather(
            self._rows(pod_id, node_id, "vlanCktEp", max_objects=MAX_VLAN_ROWS),
            _optional(self._rows(pod_id, node_id, "l2BD")),
            _optional(self._rows(pod_id, node_id, "l3Ctx")),
        )
        bridge_domains = _names_by_dn_id(domains, _BD)
        vrfs = _names_by_dn_id(contexts, _CTX)
        epgs = []
        for row in circuits:
            dn = _dn(row)
            epg_dn = text(row.get("epgDn"))
            parts = _EPG_DN.match(epg_dn or "")
            tenant, app_profile, epg = parts.groups() if parts else (None, None, None)
            encap = text(row.get("encap"))
            vlan = _ENCAP_VLAN.fullmatch(encap or "")
            epgs.append(
                AciEpg(
                    name=text(row.get("name")),
                    epg_dn=epg_dn,
                    tenant=tenant,
                    app_profile=app_profile,
                    epg=epg,
                    pc_tag=_known(row.get("pcTag")),
                    encap=encap,
                    encap_vlan=int(vlan.group(1)) if vlan else None,
                    fabric_encap=text(row.get("fabEncap")),
                    bridge_domain=bridge_domains.get(_first(_BD, dn) or ""),
                    vrf=vrfs.get(_first(_CTX, dn) or ""),
                    state=text(row.get("operSt")),
                )
            )
        return tuple(
            sorted(
                epgs,
                key=lambda e: (e.tenant or "", e.app_profile or "", e.epg or "", e.encap_vlan or 0),
            )
        )

    async def get_contracts(self, pod_id: int, node_id: int) -> AciContracts:
        """The zoning rules and filter entries the leaf enforces (``actrlRule``, ``actrlEntry``).

        The class and attribute names follow the documented MIT; the sandbox leaf has no rules, so
        they could not be checked against a live APIC.
        """
        rules, entries, circuits = await asyncio.gather(
            _optional(self._rows(pod_id, node_id, "actrlRule", max_objects=MAX_RULE_ROWS)),
            _optional(self._rows(pod_id, node_id, "actrlEntry", max_objects=MAX_FILTER_ROWS)),
            _optional(self._rows(pod_id, node_id, "vlanCktEp", max_objects=MAX_VLAN_ROWS)),
        )
        # pcTag -> EPG name, for the EPGs deployed on this leaf only.
        names = {
            tag: name
            for row in circuits
            if (tag := _known(row.get("pcTag"))) and (name := text(row.get("name")))
        }
        built_rules = []
        for row in rules:
            dn = _dn(row)
            match = _RULE_DN.search(dn)
            from_dn = match.groups() if match else (None, None, None, None)
            source = _known(row.get("sPcTag")) or from_dn[1]
            destination = _known(row.get("dPcTag")) or from_dn[2]
            built_rules.append(
                AciContractRule(
                    scope=_known(row.get("scopeId")) or from_dn[0],
                    source_pc_tag=source,
                    destination_pc_tag=destination,
                    source_epg=names.get(source or ""),
                    destination_epg=names.get(destination or ""),
                    filter_id=_known(row.get("fltId")) or from_dn[3],
                    action=text(row.get("action")),
                    direction=text(row.get("direction")),
                    priority=text(row.get("prio")),
                    state=text(row.get("operSt")),
                )
            )
        built_entries = [
            AciFilterEntry(
                filter_id=_first(_FILTER_DN, _dn(row)),
                ether_type=_known(row.get("etherT")),
                protocol=_known(row.get("prot")),
                source_port_from=_known(row.get("sFromPort")),
                source_port_to=_known(row.get("sToPort")),
                destination_port_from=_known(row.get("dFromPort")),
                destination_port_to=_known(row.get("dToPort")),
                stateful=text(row.get("stateful")),
            )
            for row in entries
        ]
        return AciContracts(
            rules=tuple(
                sorted(
                    built_rules,
                    key=lambda r: (
                        r.scope or "",
                        integer(r.source_pc_tag) or 0,
                        integer(r.destination_pc_tag) or 0,
                        r.filter_id or "",
                    ),
                )
            ),
            filters=tuple(sorted(built_entries, key=lambda f: (f.filter_id or "",))),
        )

    # --- health and faults -----------------------------------------------------------------------

    async def get_health(self, pod_id: int, node_id: int) -> AciHealth:
        node, chassis = await asyncio.gather(
            self._health_object(pod_id, node_id, "sys/health"),
            self._health_object(pod_id, node_id, "sys/ch/health"),
        )
        return AciHealth(
            score=integer(node.get("cur")),
            previous_score=integer(node.get("prev")),
            change=integer(node.get("chng")),
            max_severity=text(node.get("maxSev")),
            chassis_score=integer(chassis.get("cur")),
            chassis_previous_score=integer(chassis.get("prev")),
        )

    async def _health_object(self, pod_id: int, node_id: int, relative_dn: str) -> dict[str, Any]:
        """One health object; a missing one (HTTP 404) is empty so the other score is kept."""
        try:
            row = await self._client.get_node_mo(
                self._credentials, pod_id, node_id, relative_dn, "healthInst"
            )
        except AciNotFoundError:
            return {}
        return row or {}

    async def get_faults(self, pod_id: int, node_id: int) -> AciFaults:
        # pod/node are validated whole numbers, so nothing typed by a user is quoted here.
        query_filter = f'wcard(faultInst.dn,"topology/pod-{pod_id}/node-{node_id}/")'
        rows = await self._rows(
            pod_id, node_id, "faultInst", max_objects=MAX_FAULT_ROWS, query_filter=query_filter
        )
        counts: dict[str, int] = {}
        for row in rows:
            severity = text(row.get("severity")) or "unknown"
            counts[severity] = counts.get(severity, 0) + 1
        ordered = sorted(
            rows,
            key=lambda r: (
                _SEVERITY_RANK.get((text(r.get("severity")) or "").lower(), len(_SEVERITY_RANK)),
                text(r.get("code")) or "",
            ),
        )
        shown = ordered[:FAULT_ITEM_LIMIT]
        return AciFaults(
            total=len(rows),
            by_severity=dict(sorted(counts.items())),
            items=tuple(
                AciFault(
                    code=text(r.get("code")),
                    severity=text(r.get("severity")),
                    cause=text(r.get("cause")),
                    description=(text(r.get("descr")) or "")[:FAULT_DESCRIPTION_CHARS] or None,
                    created=text(r.get("created")),
                    lifecycle=text(r.get("lc")),
                    type=text(r.get("type")),
                    subject=text(r.get("subject")),
                    domain=text(r.get("domain")),
                    acknowledged=_flag(r.get("ack")),
                    dn=text(r.get("dn")),
                )
                for r in shown
            ),
            truncated=len(rows) > len(shown),
        )

    # --- routing and protocols -------------------------------------------------------------------

    async def get_routes(self, pod_id: int, node_id: int) -> tuple[AciRoute, ...]:
        routes, next_hops = await asyncio.gather(
            self._rows(pod_id, node_id, "ipv4Route", max_objects=MAX_ROUTE_ROWS),
            _optional(self._rows(pod_id, node_id, "ipv4Nexthop", max_objects=MAX_NEXTHOP_ROWS)),
        )
        hops_by_route: dict[tuple[str | None, str | None], list[AciNextHop]] = {}
        for row in next_hops:
            dn = _dn(row)
            key = (_first(_VRF_DOM, dn), _first(_ROUTE_PREFIX, dn))
            hops_by_route.setdefault(key, []).append(
                AciNextHop(
                    address=text(row.get("nhAddr")),
                    interface=_known(row.get("nhIf")),
                    vrf=text(row.get("nhVrf")),
                    preference=integer(row.get("pref")),
                    metric=integer(row.get("metric")),
                )
            )
        result = []
        for row in routes:
            dn = _dn(row)
            vrf, prefix = _first(_VRF_DOM, dn), text(row.get("prefix")) or _first(_ROUTE_PREFIX, dn)
            result.append(
                AciRoute(
                    vrf=vrf,
                    prefix=prefix,
                    preference=integer(row.get("pref")),
                    metric=integer(row.get("metric")),
                    next_hops=tuple(hops_by_route.get((vrf, prefix), ())),
                )
            )
        return tuple(sorted(result, key=lambda r: (r.vrf or "", r.prefix or "")))

    async def get_protocols(self, pod_id: int, node_id: int) -> AciProtocols:
        peers, entries, isis, ospf = await asyncio.gather(
            _optional(self._rows(pod_id, node_id, "bgpPeer")),
            _optional(self._rows(pod_id, node_id, "bgpPeerEntry")),
            _optional(self._rows(pod_id, node_id, "isisAdjEp")),
            _optional(self._rows(pod_id, node_id, "ospfAdjEp")),
        )
        # The session state lives on ``bgpPeerEntry`` (unverifiable on the sandbox: no rows).
        state_by_peer = {
            (_first(_VRF_DOM, _dn(row)), text(row.get("addr"))): text(row.get("operSt"))
            for row in entries
        }
        bgp = []
        for row in peers:
            vrf, address = _first(_VRF_DOM, _dn(row)), text(row.get("addr"))
            bgp.append(
                AciBgpPeer(
                    vrf=vrf,
                    address=address,
                    asn=text(row.get("asn")),
                    type=text(row.get("type")),
                    admin_state=text(row.get("adminSt")),
                    oper_state=text(row.get("operSt")) or state_by_peer.get((vrf, address)),
                )
            )
        adjacencies = [_adjacency("isis", row) for row in isis] + [
            _adjacency("ospf", row) for row in ospf
        ]
        return AciProtocols(
            bgp_peers=tuple(sorted(bgp, key=lambda p: (p.vrf or "", p.address or ""))),
            adjacencies=tuple(adjacencies),
        )

    # --- endpoints and vPC -----------------------------------------------------------------------

    async def get_endpoints(self, pod_id: int, node_id: int) -> tuple[AciEndpoint, ...]:
        ips, macs, contexts = await asyncio.gather(
            self._rows(pod_id, node_id, "epmIpEp", max_objects=MAX_ENDPOINT_ROWS),
            self._rows(pod_id, node_id, "epmMacEp", max_objects=MAX_ENDPOINT_ROWS),
            _optional(self._rows(pod_id, node_id, "l3Ctx")),
        )
        vrfs = _names_by_dn_id(contexts, _CTX)
        endpoints: list[AciEndpoint] = []
        for kind, rows in (("ip", ips), ("mac", macs)):
            for row in rows:
                address = text(row.get("addr"))
                if address is None:
                    continue
                dn = _dn(row)
                endpoints.append(
                    AciEndpoint(
                        kind=kind,  # type: ignore[arg-type]  # one of the two literals above
                        address=address,
                        interface=text(row.get("ifId")),
                        vrf=vrfs.get(_first(_CTX, dn) or ""),
                        encap_vlan=integer(_first(_DN_VLAN, dn)),
                        flags=text(row.get("flags")),
                        pc_tag=text(row.get("pcTag")),
                    )
                )
        return tuple(endpoints)

    async def get_vpc(self, pod_id: int, node_id: int) -> AciVpc:
        domains, interfaces = await asyncio.gather(
            _optional(self._rows(pod_id, node_id, "vpcDom")),
            _optional(self._rows(pod_id, node_id, "vpcIf")),
        )
        domain = domains[0] if domains else {}
        return AciVpc(
            domain_id=text(domain.get("id")),
            peer_state=text(domain.get("peerSt")),
            peer_state_reason=text(domain.get("peerStQual")),
            peer_ip=text(domain.get("peerIp")),
            role=text(domain.get("operRole")),
            virtual_ip=text(domain.get("virtualIp")),
            system_mac=_mac(domain.get("sysMac")),
            keepalive_state=text(domain.get("keepAliveSt")),
            interfaces=tuple(
                AciVpcInterface(
                    id=text(row.get("id")),
                    local_state=_known(row.get("localOperSt")),
                    remote_state=_known(row.get("remoteOperSt")),
                )
                for row in interfaces
            ),
        )


# --- joins ----------------------------------------------------------------------------------------


def _addresses_by_interface(rows: list[dict[str, Any]]) -> dict[str, list[AciInterfaceAddress]]:
    """``ipv4Addr`` objects by interface name; the interface and VRF are read from the dn."""
    by_name: dict[str, list[AciInterfaceAddress]] = {}
    for row in rows:
        dn = _dn(row)
        name, address = _first(_BRACKET_IF, dn), text(row.get("addr"))
        if name is None or address is None:
            continue
        by_name.setdefault(name, []).append(
            AciInterfaceAddress(
                address=address, type=text(row.get("type")), vrf=_first(_VRF_DOM, dn)
            )
        )
    for addresses in by_name.values():
        addresses.sort(key=lambda a: (a.type != "primary", a.address))
    return by_name


def _names_by_dn_id(rows: list[dict[str, Any]], pattern: re.Pattern[str]) -> dict[str, str]:
    """``name`` of each object keyed by the id inside the bracket of its own dn."""
    names: dict[str, str] = {}
    for row in rows:
        key, name = _first(pattern, _dn(row)), text(row.get("name"))
        if key and name:
            names[key] = name
    return names


# Operational fields copied from an IS-IS or OSPF adjacency object; anything else (an auth key, a
# policy reference) stays out of the run result. Names are best effort: the sandbox has no rows.
_ADJACENCY_FIELDS = (
    "operSt",
    "sysId",
    "type",
    "level",
    "peerIp",
    "peerId",
    "area",
    "id",
    "upTs",
)


def _adjacency(protocol: str, row: dict[str, Any]) -> AciAdjacency:
    attributes = {
        key: value for key in _ADJACENCY_FIELDS if (value := text(row.get(key))) is not None
    }
    return AciAdjacency(
        protocol=protocol,  # type: ignore[arg-type]  # "isis" or "ospf" from the callers
        state=text(row.get("operSt")),
        attributes=attributes,
    )
