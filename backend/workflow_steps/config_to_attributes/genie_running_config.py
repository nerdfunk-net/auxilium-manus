"""Build the Nautobot-ready interface list from Genie's raw running-config tree.

``get-pyats-running-config`` stores ``Device.parse("show running-config")``'s result verbatim
at ``device.parsed[parsed_key]["running"]`` (see doc/PYATS_INTEGRATION.md). That result
is a dict keyed by literal, indentation-nested CLI lines (e.g. ``"interface
Ethernet0/0": {"description xxx": {}, "ip address 10.0.0.1 255.255.255.0": {}}``) —
structurally unrelated to ``cisco_config_parser``'s flat ``l3_interfaces`` list, so it
needs its own builder producing the same output contract.
"""

from __future__ import annotations

import re
from typing import Any

from workflow_steps.common.nautobot_interfaces import (
    cidr_from_ip_and_mask,
    infer_interface_type_from_name,
)

_INTERFACE_PREFIX = "interface "
_DESCRIPTION_RE = re.compile(r"^description\s+(.*)$", re.IGNORECASE)
_IP_ADDRESS_RE = re.compile(r"^ip address (\S+) (\S+)(\s+secondary)?$", re.IGNORECASE)
_CHANNEL_GROUP_RE = re.compile(r"^channel-group\s+(\d+)(?:\s+mode\s+\S+)?$", re.IGNORECASE)
_ACCESS_VLAN_RE = re.compile(r"^switchport access vlan\s+(\d+)$", re.IGNORECASE)


def _is_shutdown(children: dict[str, Any]) -> bool:
    return any(str(key).strip().lower() == "shutdown" for key in children)


def _find_description(children: dict[str, Any]) -> str | None:
    for key in children:
        match = _DESCRIPTION_RE.match(str(key).strip())
        if match:
            description = match.group(1).strip()
            if description:
                return description
    return None


def _find_ip_addresses(children: dict[str, Any]) -> list[dict[str, Any]]:
    addresses: list[dict[str, Any]] = []
    for key in children:
        match = _IP_ADDRESS_RE.match(str(key).strip())
        if not match:
            continue
        ip_text, mask_text, secondary = match.groups()
        cidr = cidr_from_ip_and_mask(ip_text, mask_text)
        if cidr is None:
            continue
        if secondary:
            addresses.append({"address": cidr, "namespace": "Global", "ip_role": "secondary"})
        else:
            addresses.append({"address": cidr, "namespace": "Global"})
    return addresses


def _find_lag(children: dict[str, Any]) -> str | None:
    for key in children:
        match = _CHANNEL_GROUP_RE.match(str(key).strip())
        if match:
            return f"Port-channel{match.group(1)}"
    return None


def _find_access_vlan(children: dict[str, Any]) -> int | None:
    for key in children:
        match = _ACCESS_VLAN_RE.match(str(key).strip())
        if match:
            return int(match.group(1))
    return None


def _build_interface(name: str, children: Any) -> dict[str, Any] | None:
    name = name.strip()
    if not name:
        return None
    children = children if isinstance(children, dict) else {}

    iface: dict[str, Any] = {
        "name": name,
        "status": "Active",
        "type": infer_interface_type_from_name(name),
        "enabled": not _is_shutdown(children),
    }

    description = _find_description(children)
    if description:
        iface["description"] = description

    access_vlan = _find_access_vlan(children)
    if access_vlan is not None:
        iface["mode"] = "access"
        iface["untagged_vlan"] = access_vlan

    lag = _find_lag(children)
    if lag:
        iface["lag"] = lag

    ip_addresses = _find_ip_addresses(children)
    if ip_addresses:
        iface["ip_addresses"] = ip_addresses

    return iface


def build_interfaces_from_genie_running_config(
    running_config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract interfaces from a Genie-parsed ``show running-config`` tree."""
    if not isinstance(running_config, dict):
        return []

    built: list[dict[str, Any]] = []
    for key, children in running_config.items():
        line = str(key).strip()
        if not line.lower().startswith(_INTERFACE_PREFIX):
            continue
        iface = _build_interface(line[len(_INTERFACE_PREFIX) :], children)
        if iface is not None:
            built.append(iface)
    return built
