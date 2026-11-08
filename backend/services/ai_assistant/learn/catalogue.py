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

# family (neighbors.catalogue.family_of) -> feature -> commands
_TABLE: dict[str, dict[str, tuple[str, ...]]] = {"ios": {"ospf": _OSPF_IOS, "bgp": _BGP_IOS}}


class UnsupportedLearnError(ValueError):
    """The platform or feature has no catalogued command set; the message is safe to show."""


@dataclass(frozen=True)
class LearnPlan:
    feature: str
    commands: tuple[str, ...]


def plan_learn(family: str | None, feature: str) -> LearnPlan:
    """The commands that learn ``feature`` on a platform ``family``."""
    features = _TABLE.get(family or "")
    if features is None:
        raise UnsupportedLearnError(
            "Feature learn is supported for Cisco IOS / IOS-XE only so far."
        )
    commands = features.get(feature)
    if commands is None:
        raise UnsupportedLearnError(f"The feature '{feature}' is not supported on this platform.")
    return LearnPlan(feature, commands)


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
