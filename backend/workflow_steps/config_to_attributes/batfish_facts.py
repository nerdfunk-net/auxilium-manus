"""Build the Nautobot-ready interface list from Batfish's extracted facts.

``batfish-extract-facts`` writes the per-node facts dict verbatim at
``device.parsed[parsed_key]["parsed"]`` (pybatfish's own reorganized "facts"
shape — see doc/BATFISH_INTEGRATION.md's "Extract Facts" section — already
unwrapped to a single node, one level shallower than pybatfish's own
``{"nodes": {hostname: {...}}}``). Structurally unrelated to Genie's raw
running-config tree or Cisco Config Parser's flat ``l3_interfaces`` list, so
it needs its own builder producing the same output contract.

Pitfall this builder exists to get right: Batfish's ``Primary_Address`` is the
*interface's own* primary address, not Nautobot's device-level
``primary_ip4``, and it is always also present in ``All_Prefixes`` alongside
every other (secondary) address the interface carries.
"""

from __future__ import annotations

from typing import Any

from workflow_steps.config_to_attributes.genie_redundancy import vip_with_prefix
from workflow_steps.config_to_attributes.mapper_common import base_interface, positive_int, vlan_id


def _build_ip_addresses(iface: dict[str, Any]) -> list[dict[str, Any]]:
    primary = iface.get("Primary_Address")
    primary = str(primary).strip() if primary else None

    raw_prefixes = iface.get("All_Prefixes")
    prefixes = (
        [str(item).strip() for item in raw_prefixes if str(item).strip()]
        if isinstance(raw_prefixes, list)
        else []
    )

    addresses: list[str] = []
    if primary:
        addresses.append(primary)
    for prefix in prefixes:
        if prefix not in addresses:
            addresses.append(prefix)

    ip_addresses: list[dict[str, Any]] = []
    for address in addresses:
        entry: dict[str, Any] = {"address": address, "namespace": "Global"}
        if not (primary and address == primary):
            entry["ip_role"] = "secondary"
        ip_addresses.append(entry)
    return ip_addresses


def _build_redundancy_groups(
    iface: dict[str, Any], ip_addresses: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """HSRP groups from ``HSRP_Details`` (added by batfish-extract-facts from hsrpProperties).

    Batfish has no group name (``standby <n> name`` is a parse warning), so none is set; the
    Nautobot name comes from the name schema of the write step. Only the first virtual address
    of a group is the group's virtual IP. A group without one is dropped.
    """
    raw = iface.get("HSRP_Details")
    if not isinstance(raw, list):
        return []
    cidrs = [str(item["address"]) for item in ip_addresses]
    groups: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict) or item.get("Group_Id") in (None, ""):
            continue
        addresses = item.get("Virtual_Addresses")
        vip = str(addresses[0]).strip() if isinstance(addresses, list) and addresses else ""
        if not vip:
            continue
        group: dict[str, Any] = {
            "protocol": "HSRP",
            "protocol_group_id": str(item["Group_Id"]),
            "virtual_ip": {"address": vip_with_prefix(vip, cidrs)},
            "preempt": item.get("Preempt") is True,
        }
        priority = item.get("Priority")
        if isinstance(priority, int) and not isinstance(priority, bool):
            group["priority"] = priority
        groups.append(group)
    return groups


def _build_interface(name: str, iface: dict[str, Any]) -> dict[str, Any] | None:
    name = name.strip()
    if not name:
        return None

    built = base_interface(
        name, enabled=bool(iface.get("Admin_Up")), description=iface.get("Description")
    )

    mtu = positive_int(iface.get("MTU"))
    if mtu is not None:
        built["mtu"] = mtu

    if iface.get("Switchport_Mode") == "ACCESS":
        # A non-numeric or out-of-range VLAN must not fail the whole step (C2R-01).
        vlan = vlan_id(iface.get("Access_VLAN"))
        if vlan is not None:
            built["mode"] = "access"
            built["untagged_vlan"] = vlan

    channel_group = iface.get("Channel_Group")
    if channel_group:
        built["lag"] = str(channel_group)

    ip_addresses = _build_ip_addresses(iface)
    if ip_addresses:
        built["ip_addresses"] = ip_addresses

    redundancy_groups = _build_redundancy_groups(iface, ip_addresses)
    if redundancy_groups:
        built["interface_redundancy_groups"] = redundancy_groups

    return built


def interfaces_missing_hsrp_details(node_facts: dict[str, Any]) -> list[str]:
    """Interfaces that have HSRP group ids but no ``HSRP_Details`` (so no group can be built).

    Happens when ``hsrpProperties`` failed in the Extract Facts step, or when the facts come from
    an older Extract Facts that did not ask for it.
    """
    interfaces = node_facts.get("Interfaces") if isinstance(node_facts, dict) else None
    if not isinstance(interfaces, dict):
        return []
    return [
        str(name)
        for name, iface in interfaces.items()
        if isinstance(iface, dict) and iface.get("HSRP_Groups") and not iface.get("HSRP_Details")
    ]


def build_interfaces_from_batfish_facts(
    node_facts: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract interfaces from one node's Batfish ``extract_facts`` output."""
    if not isinstance(node_facts, dict):
        return []
    interfaces = node_facts.get("Interfaces")
    if not isinstance(interfaces, dict):
        return []

    built: list[dict[str, Any]] = []
    for name, iface in interfaces.items():
        if not isinstance(iface, dict):
            continue
        entry = _build_interface(str(name), iface)
        if entry is not None:
            built.append(entry)
    return built
