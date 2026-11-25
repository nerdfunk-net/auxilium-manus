"""Build Nautobot interfaces from a ``parse-cisco-config`` (cisco_config_parser) model."""

from __future__ import annotations

import re
from typing import Any

from workflow_steps.common.interface_values import (
    cidr_from_ip_and_mask,
    infer_interface_type_from_name,
)

_VLAN_RANGE_RE = re.compile(r"^(\d+)-(\d+)$")


def _base_interface(name: str, *, enabled: bool, description: Any = None) -> dict[str, Any]:
    """The fields every interface of this source starts with."""
    iface: dict[str, Any] = {
        "name": name,
        "status": "Active",
        "type": infer_interface_type_from_name(name),
        "enabled": enabled,
    }
    text = str(description or "").strip()
    if text:
        iface["description"] = text
    return iface


def _is_enabled(children: Any) -> bool:
    if not isinstance(children, list):
        return True
    return not any(str(line).strip().lower() == "shutdown" for line in children)


def _build_interface(raw: dict[str, Any]) -> dict[str, Any] | None:
    name = str(raw.get("name") or "").strip()
    if not name:
        return None

    iface = _base_interface(
        name, enabled=_is_enabled(raw.get("children")), description=raw.get("description")
    )

    ip_addresses: list[dict[str, Any]] = []
    primary_cidr = cidr_from_ip_and_mask(raw.get("ip_address"), raw.get("mask"))
    if primary_cidr:
        ip_addresses.append({"address": primary_cidr, "namespace": "Global"})

    if raw.get("sec_ip_address") and raw.get("sec_mask") and raw.get("sec_subnet"):
        secondary_cidr = cidr_from_ip_and_mask(raw.get("sec_ip_address"), raw.get("sec_mask"))
        if secondary_cidr:
            ip_addresses.append(
                {"address": secondary_cidr, "namespace": "Global", "ip_role": "secondary"}
            )

    if ip_addresses:
        iface["ip_addresses"] = ip_addresses

    return iface


def _parse_vlan_list(raw: Any) -> list[int]:
    """Parse a comma-separated VLAN id/range string into a list of ints.

    E.g. ``"10,20,30-32"`` -> ``[10, 20, 30, 31, 32]``. Best-effort: the
    cisco_config_parser library's own regex only captures a single
    ``switchport trunk allowed vlan ...`` line via ``.search()``, so a
    continuation line like ``... vlan add 50`` is already invisible upstream
    of this function — this only parses whatever single line the library did
    capture.
    """
    if not raw:
        return []
    text = str(raw).strip()
    if not text:
        return []
    vlans: list[int] = []
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        range_match = _VLAN_RANGE_RE.match(token)
        if range_match:
            start, end = int(range_match.group(1)), int(range_match.group(2))
            vlans.extend(range(start, end + 1))
        elif token.isdigit():
            vlans.append(int(token))
    return vlans


def _build_l2_access_interface(raw: dict[str, Any]) -> dict[str, Any] | None:
    name = str(raw.get("name") or "").strip()
    if not name:
        return None

    iface = _base_interface(
        name, enabled=_is_enabled(raw.get("children")), description=raw.get("description")
    )
    iface["mode"] = "access"

    try:
        data_vlan = raw.get("data_vlan")
        if data_vlan not in (None, ""):
            iface["untagged_vlan"] = int(data_vlan)
    except TypeError, ValueError:  # noqa: S110  # non-numeric VLAN: leave untagged_vlan unset
        pass

    return iface


def _build_l2_trunk_interface(raw: dict[str, Any]) -> dict[str, Any] | None:
    name = str(raw.get("name") or "").strip()
    if not name:
        return None

    iface = _base_interface(
        name, enabled=_is_enabled(raw.get("children")), description=raw.get("description")
    )
    iface["mode"] = "trunk"

    tagged_vlans = _parse_vlan_list(raw.get("allowed_vlans"))
    if tagged_vlans:
        iface["tagged_vlans"] = tagged_vlans

    return iface


def _stub_interface(name: str, description: Any = None) -> dict[str, Any]:
    """A minimal interface entry for a name only known via ``port_channels``.

    Mitigates a cisco_config_parser gap: an interface whose only
    configuration is ``channel-group N mode X`` (no IP, no switchport
    command) — and a bundle interface with neither an IP nor a switchport
    command on it — is absent from ``l3_interfaces``, ``l2_access_interfaces``,
    and ``l2_trunk_interfaces`` alike; the library only records it inside
    ``port_channels[].members``/``port_channels[].name``. Its description and
    admin (shutdown) state cannot be recovered in this case — the library
    drops the whole interface stanza — so ``enabled`` defaults to ``True``.
    """
    return _base_interface(name, enabled=True, description=description)


def _resolve_port_channel_name(port_channel: dict[str, Any]) -> str | None:
    name = str(port_channel.get("name") or "").strip()
    if name:
        return name
    po_id = str(port_channel.get("id") or "").strip()
    return f"Port-channel{po_id}" if po_id else None


def _apply_port_channels(interfaces: dict[str, dict[str, Any]], raw_port_channels: Any) -> None:
    """Fill LAG interfaces/members missing from the per-type sections above.

    Only fills gaps and adds ``lag`` — never overwrites ``mode``/
    ``tagged_vlans``/``untagged_vlan``/IP data an interface already picked up
    from ``l3_interfaces``/``l2_access_interfaces``/``l2_trunk_interfaces``.
    """
    if not isinstance(raw_port_channels, list):
        return
    for port_channel in raw_port_channels:
        if not isinstance(port_channel, dict):
            continue
        po_name = _resolve_port_channel_name(port_channel)
        if not po_name:
            continue
        if po_name not in interfaces:
            interfaces[po_name] = _stub_interface(po_name, port_channel.get("description"))

        members = port_channel.get("members")
        if not isinstance(members, list):
            continue
        for member in members:
            if not isinstance(member, dict):
                continue
            member_name = str(member.get("interface") or "").strip()
            if not member_name:
                continue
            if member_name not in interfaces:
                interfaces[member_name] = _stub_interface(member_name)
            interfaces[member_name]["lag"] = po_name


def build_interfaces_from_cisco_config(
    parsed_entry: dict[str, Any],
) -> list[dict[str, Any]]:
    interfaces: dict[str, dict[str, Any]] = {}

    for raw in parsed_entry.get("l3_interfaces") or []:
        if not isinstance(raw, dict):
            continue
        iface = _build_interface(raw)
        if iface is not None:
            interfaces[iface["name"]] = iface

    for raw in parsed_entry.get("l2_access_interfaces") or []:
        if not isinstance(raw, dict):
            continue
        iface = _build_l2_access_interface(raw)
        if iface is not None and iface["name"] not in interfaces:
            interfaces[iface["name"]] = iface

    for raw in parsed_entry.get("l2_trunk_interfaces") or []:
        if not isinstance(raw, dict):
            continue
        iface = _build_l2_trunk_interface(raw)
        if iface is not None and iface["name"] not in interfaces:
            interfaces[iface["name"]] = iface

    _apply_port_channels(interfaces, parsed_entry.get("port_channels"))

    return list(interfaces.values())
