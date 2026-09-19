"""Build the interface-list payload shared by Nautobot device write steps."""

from __future__ import annotations

import ipaddress
from typing import Any


def _strip_empty(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return value


def infer_interface_type_from_name(name: str) -> str:
    """Guess a Nautobot interface type slug from a Cisco-style interface name."""
    if "port-channel" in name.lower():
        return "lag"
    if name.startswith("Gigabit"):
        return "1000base-t"
    if name.startswith("Ethernet"):
        return "100base-tx"
    return "virtual"


def cidr_from_ip_and_mask(ip_address: Any, mask: Any) -> str | None:
    """Combine a dotted IP and dotted subnet mask into a CIDR string."""
    ip_text = str(ip_address).strip() if ip_address else ""
    mask_text = str(mask).strip() if mask else ""
    if not ip_text or not mask_text:
        return None
    try:
        prefixlen = ipaddress.IPv4Network(f"0.0.0.0/{mask_text}", strict=False).prefixlen
    except ValueError:
        return None
    return f"{ip_text}/{prefixlen}"


def build_interfaces_from_config(config: dict[str, Any], *, step_id: str) -> list[dict[str, Any]]:
    """Extract and clean the ``interfaces`` list from step config.

    Raises ``ValueError`` (prefixed with ``step_id``) when ``interfaces`` is present
    but not a list.
    """
    raw_interfaces = config.get("interfaces") or []
    if not isinstance(raw_interfaces, list):
        raise ValueError(f"{step_id}: interfaces must be a list")

    interfaces: list[dict[str, Any]] = []
    for item in raw_interfaces:
        if not isinstance(item, dict):
            continue
        name = _strip_empty(item.get("name"))
        if not name:
            continue
        iface: dict[str, Any] = {"name": name}
        for field in (
            "type",
            "status",
            "ip_address",
            "namespace",
            "description",
            "enabled",
            "mgmt_only",
            "mac_address",
            "mtu",
            "mode",
            "ip_role",
            "untagged_vlan",
            "lag",
        ):
            if field not in item:
                continue
            value = item[field]
            if field in {"enabled", "mgmt_only"}:
                if value is not None:
                    iface[field] = bool(value)
                continue
            cleaned = _strip_empty(value)
            if cleaned is not None:
                iface[field] = cleaned
        if item.get("is_primary_ipv4"):
            iface["is_primary_ipv4"] = True
        interfaces.append(iface)
    return interfaces


def normalize_interfaces(
    interfaces: list[dict[str, Any]],
    default_prefix_length: str,
) -> list[dict[str, Any]]:
    """Append ``default_prefix_length`` to any bare (no ``/nn``) interface IP address."""
    suffix = (
        default_prefix_length
        if default_prefix_length.startswith("/")
        else f"/{default_prefix_length.lstrip('/')}"
    )
    normalized: list[dict[str, Any]] = []
    for item in interfaces:
        iface = dict(item)
        ip_address = iface.get("ip_address")
        if isinstance(ip_address, str) and ip_address.strip() and "/" not in ip_address:
            iface["ip_address"] = f"{ip_address.strip()}{suffix}"
        normalized.append(iface)
    return normalized


def interfaces_from_nautobot_bag(
    bag: dict[str, Any] | None, *, default_prefix_length: str
) -> list[dict[str, Any]]:
    """Build the interfaces payload directly from a device's nautobot attribute bag.

    Unlike ``build_interfaces_from_config`` (a hand-typed config list — a fixed
    number of interfaces, one IP each, declared in advance), this reads however many
    interfaces the bag actually has, each with however many IPs it has. The plural
    ``ip_addresses`` shape is passed straight through to
    ``InterfaceManagerService.update_device_interfaces``, which already supports
    multiple IPs per interface (see ``interface.get("ip_addresses", [])`` there) —
    no new backend service support was needed for this.
    """
    if not isinstance(bag, dict):
        return []
    raw_interfaces = bag.get("interfaces")
    if not isinstance(raw_interfaces, list):
        return []

    suffix = (
        default_prefix_length
        if default_prefix_length.startswith("/")
        else f"/{default_prefix_length.lstrip('/')}"
    )

    interfaces: list[dict[str, Any]] = []
    for item in raw_interfaces:
        if not isinstance(item, dict):
            continue
        name = _strip_empty(item.get("name"))
        if not name:
            continue

        iface: dict[str, Any] = {"name": name}

        iface_type = _strip_empty(item.get("type"))
        if iface_type:
            iface["type"] = iface_type

        description = _strip_empty(item.get("description"))
        if description:
            iface["description"] = description

        status = item.get("status")
        status_name = _strip_empty(status.get("name") if isinstance(status, dict) else status)
        if status_name:
            iface["status"] = status_name

        enabled = item.get("enabled")
        if isinstance(enabled, bool):
            iface["enabled"] = enabled

        mtu = item.get("mtu")
        if isinstance(mtu, int) and mtu:
            iface["mtu"] = mtu

        mode = _strip_empty(item.get("mode"))
        if mode:
            iface["mode"] = mode

        # untagged_vlan may be a pre-resolved Nautobot VLAN UUID or a raw vid
        # (int) — resolution/creation happens downstream, at Nautobot write
        # time, so it is passed through as-is here.
        untagged_vlan = item.get("untagged_vlan")
        if untagged_vlan and untagged_vlan != "none":
            iface["untagged_vlan"] = untagged_vlan

        # lag may be a pre-resolved Nautobot interface UUID or a raw
        # interface name (e.g. "Port-channel10") — resolved downstream,
        # at Nautobot write time, against the same device's interfaces.
        lag = item.get("lag")
        if lag and lag != "none":
            iface["lag"] = lag

        raw_ip_addresses = item.get("ip_addresses")
        if isinstance(raw_ip_addresses, list):
            addresses: list[dict[str, Any]] = []
            for ip_item in raw_ip_addresses:
                is_dict = isinstance(ip_item, dict)
                address = _strip_empty(ip_item.get("address") if is_dict else ip_item)
                if not address:
                    continue
                if "/" not in address:
                    address = f"{address}{suffix}"
                entry: dict[str, Any] = {"address": address, "namespace": "Global"}
                if is_dict:
                    ip_role = _strip_empty(ip_item.get("ip_role"))
                    if ip_role and ip_role != "none":
                        entry["ip_role"] = ip_role
                    if ip_item.get("is_primary"):
                        entry["is_primary"] = True
                addresses.append(entry)
            if addresses:
                iface["ip_addresses"] = addresses

        interfaces.append(iface)

    return interfaces
