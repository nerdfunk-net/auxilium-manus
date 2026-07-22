"""Build the interface-list payload shared by Nautobot device write steps."""

from __future__ import annotations

from typing import Any


def _strip_empty(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return value


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
