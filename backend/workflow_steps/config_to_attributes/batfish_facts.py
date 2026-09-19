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

from workflow_steps.common.nautobot_interfaces import infer_interface_type_from_name


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
        if primary and address == primary:
            entry["is_primary"] = True
        else:
            entry["ip_role"] = "secondary"
        ip_addresses.append(entry)
    return ip_addresses


def _build_interface(name: str, iface: dict[str, Any]) -> dict[str, Any] | None:
    name = name.strip()
    if not name:
        return None

    built: dict[str, Any] = {
        "name": name,
        "status": "Active",
        "type": infer_interface_type_from_name(name),
        "enabled": bool(iface.get("Admin_Up")),
    }

    description = iface.get("Description")
    if isinstance(description, str) and description.strip():
        built["description"] = description.strip()

    mtu = iface.get("MTU")
    if isinstance(mtu, (int, float)) and mtu:
        built["mtu"] = int(mtu)

    access_vlan = iface.get("Access_VLAN")
    if iface.get("Switchport_Mode") == "ACCESS" and access_vlan:
        built["mode"] = "access"
        built["untagged_vlan"] = int(access_vlan)

    channel_group = iface.get("Channel_Group")
    if channel_group:
        built["lag"] = str(channel_group)

    ip_addresses = _build_ip_addresses(iface)
    if ip_addresses:
        built["ip_addresses"] = ip_addresses

    return built


def build_layer3_interfaces_from_batfish_facts(
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
