"""The reviewed catalogue of "learn a feature" command sets (doc/AI_TOOL_CHAIN.md §49).

``pyats learn <feature>`` runs a fixed group of show commands and merges their parsed output into
one model. This catalogue holds that group per platform family and feature, so the model only names
a feature from a closed set and never writes command text. A test checks that every command passes
the read-only command policy and fits the signed-command limit.

The lists were read from a real run (``pyats learn ospf --testbed-file ... -v``, IOS-XE 17.15 IOL,
``os: ios``, default VRF only). Two commands Genie also ran are left out on purpose:

* ``show running-config | section router ospf <pid>`` needs the process id from earlier output, and
  ``show ip ospf`` / ``show ip protocols`` already carry it.
* ``show ip ospf interface <name>`` repeats ``show ip ospf interface`` for one interface.

Other families and features are refused with a fixed message rather than guessed.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass

FEATURES: tuple[str, ...] = ("ospf", "bgp")

# Order matters: the stored output is cut at a total size (device_exec_service.MAX_OUTPUT_CHARS)
# and the cut drops the LAST commands. The small outputs the report is built from come first; the
# link-state database, which can be larger than the whole cap on a real area, comes last.
_OSPF_IOS: tuple[str, ...] = (
    "show ip ospf",
    "show ip protocols",
    "show ip ospf interface",
    "show ip ospf neighbor detail",
    "show ip ospf virtual-links",
    "show ip ospf sham-links",
    "show ip ospf mpls ldp interface",
    "show ip ospf mpls traffic-eng link",
    "show ip ospf database router",
    "show ip ospf database network",
    "show ip ospf database external",
    "show ip ospf database summary",
    "show ip ospf database opaque-area",
)

# Read from the installed Genie Ops source (genie.libs.ops.bgp.iosxe.bgp and the parser classes),
# not from a run: the lab had no BGP. Only commands that need no earlier output are here. Genie also
# runs, per neighbour, address family or VRF: ``show bgp all neighbors <n> policy`` and its
# ``advertised-routes``, ``received-routes`` and ``routes`` forms, and ``show bgp vrf <v> all
# summary``. They are left out: the route commands can return whole BGP tables, and the rest needs
# values from these outputs.
_BGP_IOS: tuple[str, ...] = (
    "show bgp all summary",
    "show bgp all neighbors",
    "show bgp all cluster-ids",
    "show ip bgp template peer-policy",
    "show ip bgp template peer-session",
    "show ip bgp all dampening parameters",
    "show bgp all detail",  # the BGP table: can be very large, so it goes last
)

# The same reading for one named VRF (doc/plans/BGP_PLAYBOOK.md step 2), IPv4 unicast only. Not
# run on a device yet. These are the forms the Genie IOS-XE parsers register (``ShowBgpAllSummary``:
# ``show bgp vrf {vrf} all summary``; ``ShowBgpNeighbors`` / ``ShowBgpDetail``: ``show bgp
# {address_family} vrf {vrf} neighbors|detail``), so every command parses. ``show bgp vrf {vrf} all
# neighbors`` and ``... all detail`` have no parser. The table goes last, as in the default VRF.
_BGP_VRF_IOS: tuple[str, ...] = (
    "show bgp vrf {vrf} all summary",
    "show bgp ipv4 unicast vrf {vrf} neighbors",
    "show bgp ipv4 unicast vrf {vrf} detail",
)
_VRF_TABLE: dict[str, dict[str, tuple[str, ...]]] = {"ios": {"bgp": _BGP_VRF_IOS}}

DEFAULT_VRF = "default"
_VRF = re.compile(r"[A-Za-z0-9_.-]{1,32}")

# family (neighbors.catalogue.family_of) -> feature -> commands
_TABLE: dict[str, dict[str, tuple[str, ...]]] = {"ios": {"ospf": _OSPF_IOS, "bgp": _BGP_IOS}}


class UnsupportedLearnError(ValueError):
    """The platform or feature has no catalogued command set; the message is safe to show."""


@dataclass(frozen=True)
class LearnPlan:
    feature: str
    commands: tuple[str, ...]


def plan_learn(family: str | None, feature: str, vrf: str = DEFAULT_VRF) -> LearnPlan:
    """The commands that learn ``feature`` on a platform ``family`` (default VRF, or ``vrf``)."""
    if vrf != DEFAULT_VRF:
        return _plan_vrf(family, feature, vrf)
    features = _TABLE.get(family or "")
    if features is None:
        raise UnsupportedLearnError(
            "Feature learn is supported for Cisco IOS / IOS-XE only so far."
        )
    commands = features.get(feature)
    if commands is None:
        raise UnsupportedLearnError(f"The feature '{feature}' is not supported on this platform.")
    return LearnPlan(feature, commands)


def _check_vrf(vrf: str) -> None:
    if not _VRF.fullmatch(vrf):
        raise UnsupportedLearnError(
            "A VRF name is 1 to 32 letters, digits, '.', '_' or '-', or 'default'."
        )


def _plan_vrf(family: str | None, feature: str, vrf: str) -> LearnPlan:
    _check_vrf(vrf)
    if family not in _TABLE:
        raise UnsupportedLearnError(
            "Feature learn is supported for Cisco IOS / IOS-XE only so far."
        )
    templates = _VRF_TABLE.get(family or "", {}).get(feature)
    if templates is None:
        raise UnsupportedLearnError(f"The feature '{feature}' is not supported for a VRF yet.")
    return LearnPlan(feature, tuple(t.format(vrf=vrf) for t in templates))


def is_plan(commands: tuple[str, ...] | list[str]) -> bool:
    """Whether ``commands`` is exactly one catalogued plan (any family and feature).

    The confirm step allows more than the free-form limit only for such a list, so a token that
    carries other commands is held to the small limit.
    """
    wanted = tuple(commands)
    return any(wanted == plan for features in _TABLE.values() for plan in features.values())


def supported(family: str | None) -> list[str]:
    """The features the catalogue offers for a platform family."""
    return sorted(_TABLE.get(family or "", {}))


# One neighbour of a BGP learn (doc/plans/BGP_PLAYBOOK.md step 1). The address is substituted into
# these templates only after ``parse_neighbor_address``; route lists are never dumped, only the
# "Total number of prefixes N" line that ends them (the genie parser reads it, see
# ``genie_parser.filtered_total``). A bare ``| count`` is not used: it counts header lines and some
# releases want a pattern after it.
TOTAL_FILTER = "| include Total number of prefixes"
_BGP_NEIGHBOR_IOS: tuple[str, ...] = (
    "show bgp all neighbors {n} policy",
    f"show bgp all neighbors {{n}} advertised-routes {TOTAL_FILTER}",
    f"show bgp all neighbors {{n}} received-routes {TOTAL_FILTER}",
)
# A neighbour inside a VRF is read with the address family before ``vrf`` (Genie's forms).
_BGP_NEIGHBOR_VRF_IOS: tuple[str, ...] = (
    "show bgp ipv4 unicast vrf {vrf} neighbors {n} policy",
    f"show bgp ipv4 unicast vrf {{vrf}} neighbors {{n}} advertised-routes {TOTAL_FILTER}",
    f"show bgp ipv4 unicast vrf {{vrf}} neighbors {{n}} received-routes {TOTAL_FILTER}",
)
_NEIGHBOR_TABLE: dict[str, tuple[str, ...]] = {"ios": _BGP_NEIGHBOR_IOS}
_NEIGHBOR_VRF_TABLE: dict[str, tuple[str, ...]] = {"ios": _BGP_NEIGHBOR_VRF_IOS}


def parse_neighbor_address(value: str) -> str:
    """The canonical text of exactly one IPv4 or IPv6 address, else ``UnsupportedLearnError``.

    No host names, prefixes, scope ids, spaces, pipes or command words can pass: the result is
    rebuilt from the parsed address, never echoed from the input.
    """
    if not isinstance(value, str) or value != value.strip() or not value:
        raise UnsupportedLearnError("The neighbour must be one IPv4 or IPv6 address.")
    if not all(c in "0123456789abcdefABCDEF.:" for c in value):
        raise UnsupportedLearnError("The neighbour must be one IPv4 or IPv6 address.")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        raise UnsupportedLearnError("The neighbour must be one IPv4 or IPv6 address.") from None


def plan_bgp_neighbor(family: str | None, neighbor: str, vrf: str = DEFAULT_VRF) -> LearnPlan:
    """The commands that read one BGP neighbour's policy and its prefix totals."""
    table = _NEIGHBOR_TABLE if vrf == DEFAULT_VRF else _NEIGHBOR_VRF_TABLE
    templates = table.get(family or "")
    if templates is None:
        raise UnsupportedLearnError(
            "Feature learn is supported for Cisco IOS / IOS-XE only so far."
        )
    address = parse_neighbor_address(neighbor)
    if vrf != DEFAULT_VRF:
        _check_vrf(vrf)
    return LearnPlan("bgp-neighbor", tuple(t.format(n=address, vrf=vrf) for t in templates))
