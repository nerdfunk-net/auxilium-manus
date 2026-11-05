"""The reviewed catalogue of read-only neighbour discovery commands (doc/AI_TOOL_CHAIN.md §24.5).

The one source of commands for ``propose_neighbor_discovery``: the model chooses a layer, a routing
protocol and a VRF from closed sets, never command text. Each entry names the command, the
command with a VRF (``None`` when the platform or its TextFSM template has no per-VRF form) and
what the parsed rows mean. A test checks that every entry passes the read-only command policy and
that ntc-templates has a template for every command that is parsed.

Platforms without an entry (Comware, ASA, ...) and combinations without a template (the Junos RIB,
per-VRF IS-IS and EIGRP, ...) are refused with a fixed message rather than guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Layer = Literal["l2", "l3"]
Family = Literal["ios", "nxos", "xr", "eos", "junos"]

FAMILIES: tuple[str, ...] = ("ios", "nxos", "xr", "eos", "junos")
DEFAULT_VRF = "default"
MAX_VRF_CHARS = 32
_VRF = re.compile(r"[A-Za-z0-9_.-]{1,32}")

_FAMILY_OF_NETMIKO_TYPE = {
    "cisco_ios": "ios",
    "cisco_xe": "ios",
    "cisco_nxos": "nxos",
    "cisco_xr": "xr",
    "arista_eos": "eos",
    "juniper_junos": "junos",
}


class UnsupportedDiscoveryError(ValueError):
    """The platform, layer, protocol or VRF has no catalogued command; the message is safe."""


@dataclass(frozen=True)
class Entry:
    layer: str
    protocol: str
    command: str
    # The command with ``{vrf}`` where the VRF name goes; ``None`` = not supported per VRF.
    vrf_command: str | None = None


@dataclass(frozen=True)
class Step:
    """One command of a plan and what its output means."""

    command: str
    layer: str
    protocol: str
    vrf: str


@dataclass(frozen=True)
class DiscoveryPlan:
    steps: tuple[Step, ...]
    # ``textfsm`` for neighbour tables, ``none`` for protocol discovery (the model reads the text).
    parser: str

    @property
    def commands(self) -> list[str]:
        return [step.command for step in self.steps]


def _l2(cdp: bool = True, lldp: str | None = "show lldp neighbors detail") -> list[Entry]:
    entries = []
    if cdp:
        entries.append(Entry("l2", "cdp", "show cdp neighbors detail"))
    if lldp:
        entries.append(Entry("l2", "lldp", lldp))
    return entries


_ROUTE = "routing_table"
_TABLE: dict[str, list[Entry]] = {
    "ios": [
        *_l2(),
        Entry("l3", _ROUTE, "show ip route", "show ip route vrf {vrf}"),
        Entry("l3", "ospf", "show ip ospf neighbor"),
        Entry("l3", "bgp", "show ip bgp summary"),
        Entry("l3", "eigrp", "show ip eigrp neighbors"),
        Entry("l3", "isis", "show isis neighbors"),
    ],
    "nxos": [
        *_l2(),
        Entry("l3", _ROUTE, "show ip route", "show ip route vrf {vrf}"),
        Entry("l3", "ospf", "show ip ospf neighbors", "show ip ospf neighbors vrf {vrf}"),
        Entry("l3", "bgp", "show ip bgp summary", "show ip bgp summary vrf {vrf}"),
        Entry("l3", "eigrp", "show ip eigrp neighbors"),
    ],
    "xr": [
        *_l2(),
        Entry("l3", _ROUTE, "show route", "show route vrf {vrf}"),
        Entry("l3", "ospf", "show ospf neighbor", "show ospf vrf {vrf} neighbor"),
        Entry("l3", "bgp", "show ip bgp summary"),
        Entry("l3", "eigrp", "show eigrp neighbors"),
        Entry("l3", "isis", "show isis neighbors"),
    ],
    "eos": [
        *_l2(cdp=False),
        Entry("l3", _ROUTE, "show ip route", "show ip route vrf {vrf}"),
        Entry("l3", "ospf", "show ip ospf neighbor"),
        Entry("l3", "bgp", "show ip bgp summary", "show ip bgp summary vrf {vrf}"),
        Entry("l3", "isis", "show isis neighbors"),
    ],
    "junos": [
        *_l2(cdp=False, lldp="show lldp neighbors"),
        Entry("l3", "ospf", "show ospf neighbor"),
        Entry("l3", "bgp", "show bgp summary"),
        Entry("l3", "isis", "show isis adjacency"),
    ],
}

# Protocol discovery: short outputs the model reads as text (``show ip protocols`` has no template
# on any platform, §24.14). Protocols present in the RIB and the VRF names come out of these.
_DISCOVER: dict[str, tuple[str, ...]] = {
    "ios": ("show ip protocols", "show ip route summary", "show vrf"),
    "nxos": ("show ip route summary", "show vrf"),
    "xr": ("show route summary", "show vrf all detail"),
    "eos": ("show ip route summary", "show vrf"),
    "junos": ("show route summary", "show route instance"),
}


def family_of(netmiko_type: str | None) -> str | None:
    """The catalogue family of a Netmiko device type, or ``None`` for an unsupported platform."""
    return _FAMILY_OF_NETMIKO_TYPE.get(netmiko_type or "")


def _check_vrf(vrf: str) -> str:
    if vrf != DEFAULT_VRF and not _VRF.fullmatch(vrf):
        raise UnsupportedDiscoveryError(
            f"A VRF name is 1 to {MAX_VRF_CHARS} letters, digits, '.', '_' or '-', or 'default'."
        )
    return vrf


def _step(entry: Entry, vrf: str) -> Step:
    if entry.layer == "l2" or vrf == DEFAULT_VRF:
        return Step(entry.command, entry.layer, entry.protocol, DEFAULT_VRF)
    if entry.vrf_command is None:
        raise UnsupportedDiscoveryError(
            f"{entry.protocol} neighbours are not supported for a VRF on this platform."
        )
    return Step(entry.vrf_command.format(vrf=vrf), entry.layer, entry.protocol, vrf)


def plan_discovery(family: str, layer: str, protocol: str, vrf: str) -> DiscoveryPlan:
    """The commands for ``layer`` (``l2``, ``l3`` or ``both``), routing ``protocol`` and ``vrf``."""
    vrf = _check_vrf(vrf)
    entries = _TABLE.get(family)
    if entries is None:
        raise UnsupportedDiscoveryError("Neighbour discovery is not supported for this platform.")
    if layer == "l3" and protocol == "discover":
        return DiscoveryPlan(
            tuple(Step(c, "l3", "discover", DEFAULT_VRF) for c in _DISCOVER[family]), "none"
        )
    steps: list[Step] = []
    if layer in ("l2", "both"):
        steps.extend(_step(e, vrf) for e in entries if e.layer == "l2")
    if layer in ("l3", "both"):
        l3 = [e for e in entries if e.layer == "l3" and e.protocol == protocol]
        if not l3:
            raise UnsupportedDiscoveryError(
                f"{protocol} neighbours are not supported on this platform."
            )
        steps.extend(_step(e, vrf) for e in l3)
    if not steps:
        raise UnsupportedDiscoveryError("Nothing to discover for that layer on this platform.")
    return DiscoveryPlan(tuple(steps), "textfsm")


def supported(family: str) -> dict[str, list[str]]:
    """What the catalogue offers for a family: protocols per layer and the VRF-capable ones."""
    entries = _TABLE.get(family, [])
    return {
        "l2": [e.protocol for e in entries if e.layer == "l2"],
        "l3": [e.protocol for e in entries if e.layer == "l3"],
        "l3_with_vrf": [e.protocol for e in entries if e.layer == "l3" and e.vrf_command],
        "discover": ["discover"] if family in _DISCOVER else [],
    }


def _vrf_pattern(template: str) -> re.Pattern[str]:
    return re.compile(re.escape(template).replace(r"\{vrf\}", r"(?P<vrf>[A-Za-z0-9_.\-]{1,32})"))


def classify_command(family: str, command: str) -> Step | None:
    """What a command of a stored output meant, or ``None`` when the catalogue did not ask it.

    The stored output carries the commands that were run; this turns each back into a layer, a
    protocol and a VRF, so a command that is not in the catalogue is never read as a neighbour.
    """
    for entry in _TABLE.get(family, []):
        if command == entry.command:
            return Step(entry.command, entry.layer, entry.protocol, DEFAULT_VRF)
        if entry.vrf_command:
            found = _vrf_pattern(entry.vrf_command).fullmatch(command)
            if found:
                return Step(command, entry.layer, entry.protocol, found.group("vrf"))
    if command in _DISCOVER.get(family, ()):
        return Step(command, "l3", "discover", DEFAULT_VRF)
    return None
