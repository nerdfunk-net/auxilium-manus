"""HSRP / VRRP redundancy groups from one interface's Genie running-config lines.

Genie keeps each CLI line as a dict key, e.g. ``"standby 0 ip 192.168.180.100"``. The result
mirrors what ``get-nautobot-attributes`` returns per interface (``interface_redundancy_groups``),
so the Nautobot write step reads one shape. Authentication lines (``standby 1 authentication
md5 key-string ...``) are never read: a secret must not land in the attribute bag.

Supported: HSRP (``standby [G] ip|priority|preempt|name``) and legacy VRRP
(``vrrp G ip|priority|preempt|description``). The IOS-XE ``vrrp G address-family ipv4`` block,
IPv6 and ``standby timers/track`` are not read.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_HSRP = re.compile(r"^standby\s+(?:(\d+)\s+)?(ip|priority|preempt|name)\b\s*(.*)$", re.IGNORECASE)
_VRRP = re.compile(r"^vrrp\s+(\d+)\s+(ip|priority|preempt|description)\b\s*(.*)$", re.IGNORECASE)
_PRIORITY = re.compile(r"^(\d+)\b")
# IOS-XE VRRPv3 block (``vrrp 1 address-family ipv4`` with nested ``address ...``): not read.
_VRRP_ADDRESS_FAMILY = re.compile(r"^vrrp\s+\d+\s+address-family\b", re.IGNORECASE)


def vip_with_prefix(vip: str, interface_cidrs: list[str]) -> str:
    """``vip`` as CIDR when it lies in one of the interface's own networks, else bare."""
    try:
        vip_ip = ipaddress.IPv4Address(vip)
    except ValueError:
        return vip
    for cidr in interface_cidrs:
        try:
            network = ipaddress.IPv4Interface(cidr).network
        except ValueError:
            logger.debug("Ignoring unparsable interface address %r", cidr)
            continue
        if vip_ip in network:
            return f"{vip}/{network.prefixlen}"
    return vip


def _apply_line(group: dict[str, Any], field: str, rest: str) -> None:
    field = field.lower()
    rest = rest.strip()
    if field == "ip":
        tokens = rest.split()
        # A secondary virtual IP is not the group's virtual IP.
        if tokens and "secondary" not in (t.lower() for t in tokens[1:]):
            group["vip"] = tokens[0]
    elif field == "priority":
        match = _PRIORITY.match(rest)
        if match:
            group["priority"] = int(match.group(1))
    elif field == "preempt":
        group["preempt"] = True
    elif field in ("name", "description") and rest:
        group[field] = rest


def _collect(children: dict[str, Any]) -> dict[tuple[str, int], dict[str, Any]]:
    groups: dict[tuple[str, int], dict[str, Any]] = {}
    for key in children:
        line = str(key).strip()
        hsrp, vrrp = _HSRP.match(line), _VRRP.match(line)
        if hsrp:
            protocol, match = "HSRP", hsrp
        elif vrrp:
            protocol, match = "VRRP", vrrp
        else:
            continue
        group_id = int(match.group(1) or 0)
        _apply_line(groups.setdefault((protocol, group_id), {}), match.group(2), match.group(3))
    return groups


def find_redundancy_groups(
    interface_name: str, children: dict[str, Any], interface_cidrs: list[str]
) -> list[dict[str, Any]]:
    """The interface's HSRP/VRRP groups (those with a virtual IP), ordered by protocol and id."""
    built: list[dict[str, Any]] = []
    for (protocol, group_id), raw in sorted(_collect(children).items()):
        vip = raw.get("vip")
        if not vip:
            continue
        group: dict[str, Any] = {
            "name": raw.get("name") or f"{interface_name}-{protocol}-{group_id}",
            "protocol": protocol,
            "protocol_group_id": str(group_id),
            "virtual_ip": {"address": vip_with_prefix(vip, interface_cidrs)},
            "preempt": bool(raw.get("preempt")),
        }
        if "priority" in raw:
            group["priority"] = raw["priority"]
        # The device's own text: the HSRP group name or the VRRP description.
        description = raw.get("description") or raw.get("name")
        if description:
            group["description"] = description
        built.append(group)
    return built


def interfaces_with_unsupported_redundancy(running_config: dict[str, Any]) -> list[str]:
    """Interfaces whose VRRP configuration is in the IOS-XE ``address-family`` form.

    That form is not read, so such an interface gets no group; the step reports it instead of
    succeeding silently. An interface that also has a readable group is not listed.
    """
    names: list[str] = []
    if not isinstance(running_config, dict):
        return names
    for key, children in running_config.items():
        line = str(key).strip()
        if not line.lower().startswith("interface ") or not isinstance(children, dict):
            continue
        if any(_VRRP_ADDRESS_FAMILY.match(str(child).strip()) for child in children) and not any(
            _VRRP.match(str(child).strip()) for child in children
        ):
            names.append(line[len("interface ") :].strip())
    return names
