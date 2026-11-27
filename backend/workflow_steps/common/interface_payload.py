"""Build the interface-list payload shared by Nautobot device write steps."""

from __future__ import annotations

import logging
from typing import Any

from workflow_steps.common.interface_values import (
    apply_normalized_fields,
    apply_text_fields,
    infer_interface_type_from_name,
    lower_text,
    strip_empty,
    text_cell,
)
from workflow_steps.common.redundancy_groups import ip_namespace_name, redundancy_groups_from_bag

logger = logging.getLogger(__name__)


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
        name = strip_empty(item.get("name"))
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
            cleaned = strip_empty(value)
            if cleaned is not None:
                iface[field] = cleaned
        apply_normalized_fields(iface, item)
        tagged_vlans = item.get("tagged_vlans")
        if isinstance(tagged_vlans, list):
            cleaned_tagged_vlans = [v for v in tagged_vlans if v not in (None, "")]
            if cleaned_tagged_vlans:
                iface["tagged_vlans"] = cleaned_tagged_vlans
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


def _prefix_suffix(default_prefix_length: str) -> str:
    """``"/24"`` for ``"24"`` or ``"/24"``: what a bare bag address gets appended."""
    if default_prefix_length.startswith("/"):
        return default_prefix_length
    return f"/{default_prefix_length.lstrip('/')}"


def _basic_fields(item: dict[str, Any], name: str) -> dict[str, Any]:
    """Name, type, description, status and enabled, as far as the bag has them (text only)."""
    iface: dict[str, Any] = {"name": name}
    for field in ("type", "description"):
        text = text_cell(item.get(field), interface=name, field=field)
        if text:
            iface[field] = text
    status = item.get("status")
    status_name = text_cell(
        status.get("name") if isinstance(status, dict) else status, interface=name, field="status"
    )
    if status_name:
        iface["status"] = status_name
    enabled = item.get("enabled")
    if isinstance(enabled, bool):
        iface["enabled"] = enabled
    return iface


def _reference(value: Any, *, interface: str, field: str) -> str | int | None:
    """A VLAN or LAG reference of the bag: an int vid, or text (a vid, a UUID, an interface
    name). The empty markers (``None``, ``0``, ``""``, ``"none"``) go; anything else that is not
    text is logged by field and left out (``text_cell``)."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value or None
    text = text_cell(value, interface=interface, field=field)
    return None if text in (None, "none") else text


def _clean_vlans(iface: dict[str, Any], item: dict[str, Any]) -> None:
    """Untagged VLAN, LAG and tagged VLANs.

    Each may be a pre-resolved Nautobot UUID or a raw value (a vid, an interface name such as
    ``Port-channel10``): resolution and creation happen downstream, at Nautobot write time, so
    they pass through as they are (``_reference``).
    """
    name = iface["name"]
    for field in ("untagged_vlan", "lag"):
        reference = _reference(item.get(field), interface=name, field=field)
        if reference is not None:
            iface[field] = reference
    tagged_vlans = item.get("tagged_vlans")
    if isinstance(tagged_vlans, list):
        cleaned = [
            reference
            for value in tagged_vlans
            if (reference := _reference(value, interface=name, field="tagged_vlans")) is not None
        ]
        if cleaned:
            iface["tagged_vlans"] = cleaned


def _clean_ip_addresses(raw: Any, suffix: str, *, interface: str) -> list[dict[str, Any]]:
    """The bag's addresses (dicts or bare text), with ``suffix`` on an address without a length,
    the namespace (``Global`` when the bag names none), the role and the primary flag. An address
    or role that is not text is left out (``text_cell``)."""
    if not isinstance(raw, list):
        return []
    addresses: list[dict[str, Any]] = []
    for ip_item in raw:
        is_dict = isinstance(ip_item, dict)
        address = text_cell(
            ip_item.get("address") if is_dict else ip_item,
            interface=interface,
            field="ip_addresses",
        )
        if not address:
            continue
        if "/" not in address:
            address = f"{address}{suffix}"
        namespace = (ip_namespace_name(ip_item) if is_dict else None) or "Global"
        entry: dict[str, Any] = {"address": address, "namespace": namespace}
        if is_dict:
            ip_role = text_cell(ip_item.get("ip_role"), interface=interface, field="ip_role")
            if ip_role and ip_role != "none":
                entry["ip_role"] = ip_role
            if ip_item.get("is_primary"):
                entry["is_primary"] = True
        addresses.append(entry)
    return addresses


def _bag_interface(item: Any, suffix: str) -> dict[str, Any] | None:
    """One interface of the bag as the write expects it, or ``None`` for an entry without a name."""
    if not isinstance(item, dict):
        return None
    name = text_cell(item.get("name"), interface=None, field="name")
    if not name:
        return None
    iface = _basic_fields(item, name)
    # mac_address, mtu, mode, port_type, speed, duplex, vrf (normalized to Nautobot's forms)
    apply_normalized_fields(iface, item)
    _clean_vlans(iface, item)
    addresses = _clean_ip_addresses(item.get("ip_addresses"), suffix, interface=name)
    if addresses:
        iface["ip_addresses"] = addresses
    redundancy_groups = redundancy_groups_from_bag(
        item.get("interface_redundancy_groups"), iface.get("ip_addresses", [])
    )
    if redundancy_groups:
        iface["interface_redundancy_groups"] = redundancy_groups
    return iface


def interfaces_from_nautobot_bag(
    bag: dict[str, Any] | None, *, default_prefix_length: str
) -> list[dict[str, Any]]:
    """Build the interfaces payload directly from a device's nautobot attribute bag.

    Unlike ``build_interfaces_from_config`` (a hand-typed config list — a fixed
    number of interfaces, one IP each, declared in advance), this reads however many
    interfaces the bag actually has, each with however many IPs it has. The plural
    ``ip_addresses`` shape is passed straight through to
    ``InterfaceManagerService.update_device_interfaces``, which already supports
    multiple IPs per interface (see ``interface.get("ip_addresses", [])`` there).
    """
    if not isinstance(bag, dict):
        return []
    raw_interfaces = bag.get("interfaces")
    if not isinstance(raw_interfaces, list):
        return []
    suffix = _prefix_suffix(default_prefix_length)
    return [iface for item in raw_interfaces if (iface := _bag_interface(item, suffix)) is not None]


NEW_TYPE_MODES = frozenset({"none", "infer", "fixed"})


def interfaces_from_parsed_list(
    rows: Any,
    field_map: dict[str, str],
    *,
    fixed_values: dict[str, Any] | None = None,
    new_type_mode: str = "none",
    new_type_value: str = "",
) -> list[dict[str, Any]]:
    """Build the interfaces payload from a parsed list of dicts (e.g. TextFSM ``show interfaces``).

    ``field_map`` maps an interface field (``name``, ``mac_address``, ``mtu``, ``speed``,
    ``duplex``, ``port_type``, ``mode``, ``vrf``, ``type``, ``description``) to the column that
    holds it. ``name`` is required. ``fixed_values`` sets a field to the same value on every
    row (for example ``type`` - TextFSM output has no Nautobot interface type, but a new
    interface cannot be created without one). A column cell that is blank leaves that field out,
    so an existing Nautobot value is not wiped. Rows without a name, and non-dict rows, are skipped.

    ``new_type_mode`` sets ``type_if_new``, a type used ONLY when the interface does not exist yet
    (the interface workflow ignores it for an existing interface, unlike ``type``, which is always
    patched): ``none`` adds nothing, ``infer`` guesses it from the interface name
    (``infer_interface_type_from_name``), ``fixed`` uses ``new_type_value`` for every row.
    """
    if new_type_mode not in NEW_TYPE_MODES:
        raise ValueError(f"parsed list: new_type_mode must be one of {sorted(NEW_TYPE_MODES)}")
    fixed_new_type = lower_text(new_type_value) if new_type_mode == "fixed" else None
    if new_type_mode == "fixed" and not fixed_new_type:
        raise ValueError("parsed list: new_type_mode 'fixed' needs a type value")

    name_column = strip_empty(field_map.get("name"))
    if not name_column:
        raise ValueError("parsed list: the 'name' column mapping is required")
    if not isinstance(rows, list):
        raise ValueError("parsed list: the attribute path must resolve to a list of objects")

    interfaces: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = strip_empty(row.get(name_column))
        if not isinstance(name, str):
            continue
        source: dict[str, Any] = dict(fixed_values or {})
        for field, column in field_map.items():
            if field == "name" or not column or column not in row:
                continue
            cell = row[column]
            # A blank cell leaves the fixed value (or nothing) in place; it never erases it.
            if cell is None or (isinstance(cell, str) and not cell.strip()):
                continue
            source[field] = cell
        iface: dict[str, Any] = {"name": name}
        apply_text_fields(iface, source)
        apply_normalized_fields(iface, source)
        if new_type_mode == "infer":
            iface["type_if_new"] = infer_interface_type_from_name(name)
        elif fixed_new_type:
            iface["type_if_new"] = fixed_new_type
        interfaces.append(iface)
    return interfaces
