"""Select which interface's address becomes a device's Nautobot primary IPv4.

A Cisco config never states "this is my primary IPv4" — that's an operational
convention, not a config line. This module implements the two policies the
config-to-attributes executor offers: pick one interface by a priority-ordered
list of strategies, or verify the device's already-known primary IPv4 is still
present in the parsed config (and re-affirm it) without picking a new one.
"""

from __future__ import annotations

import re
from typing import Any

_MANAGEMENT_NAME_RE = re.compile(r"^(management|mgmt)", re.IGNORECASE)
_LOOPBACK_NUMBER_RE = re.compile(r"^loopback(\d+)$", re.IGNORECASE)

PRIORITY_STRATEGIES = frozenset(
    {"management_interface", "loopback_highest", "loopback_lowest", "custom_interface"}
)


def bare_ip(address: str) -> str:
    """Strip a trailing ``/nn`` prefix length, if present."""
    return address.split("/")[0].strip()


def _interface_addresses(interface: dict[str, Any]) -> list[dict[str, Any]]:
    raw = interface.get("ip_addresses")
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def interface_primary_candidate(interface: dict[str, Any]) -> str | None:
    """This interface's own main (non-secondary) address, or ``None``."""
    for entry in _interface_addresses(interface):
        if entry.get("ip_role") == "secondary":
            continue
        address = entry.get("address")
        if isinstance(address, str) and address.strip():
            return address.strip()
    return None


def device_primary_ip_present(interfaces: list[dict[str, Any]], primary_ip4: str) -> bool:
    """Whether ``primary_ip4`` (any prefix length) appears on any interface's any address."""
    target = bare_ip(primary_ip4)
    for interface in interfaces:
        for entry in _interface_addresses(interface):
            address = entry.get("address")
            if isinstance(address, str) and bare_ip(address) == target:
                return True
    return False


def find_interface_for_ip(
    interfaces: list[dict[str, Any]], primary_ip4: str
) -> tuple[str, str] | None:
    """Locate the ``(interface_name, address)`` pair whose address matches ``primary_ip4``."""
    target = bare_ip(primary_ip4)
    for interface in interfaces:
        name = interface.get("name")
        if not isinstance(name, str):
            continue
        for entry in _interface_addresses(interface):
            address = entry.get("address")
            if isinstance(address, str) and bare_ip(address) == target:
                return name, address
    return None


def _select_management(interfaces: list[dict[str, Any]]) -> tuple[str, str] | None:
    for interface in interfaces:
        name = interface.get("name")
        if not isinstance(name, str) or not _MANAGEMENT_NAME_RE.match(name):
            continue
        address = interface_primary_candidate(interface)
        if address:
            return name, address
    return None


def _select_loopback(interfaces: list[dict[str, Any]], *, highest: bool) -> tuple[str, str] | None:
    candidates: list[tuple[int, str, str]] = []
    for interface in interfaces:
        name = interface.get("name")
        if not isinstance(name, str):
            continue
        match = _LOOPBACK_NUMBER_RE.match(name)
        if not match:
            continue
        address = interface_primary_candidate(interface)
        if address:
            candidates.append((int(match.group(1)), name, address))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=highest)
    _, name, address = candidates[0]
    return name, address


def _select_custom(interfaces: list[dict[str, Any]], pattern: str) -> tuple[str, str] | None:
    if not pattern:
        return None
    compiled = re.compile(pattern, re.IGNORECASE)
    for interface in interfaces:
        name = interface.get("name")
        if not isinstance(name, str) or not compiled.search(name):
            continue
        address = interface_primary_candidate(interface)
        if address:
            return name, address
    return None


def select_primary_ipv4(
    interfaces: list[dict[str, Any]],
    priority: list[str],
    custom_pattern: str,
) -> tuple[str, str] | None:
    """Walk ``priority`` in order; return the first strategy's match, or ``None``."""
    for strategy in priority:
        if strategy == "management_interface":
            result = _select_management(interfaces)
        elif strategy == "loopback_highest":
            result = _select_loopback(interfaces, highest=True)
        elif strategy == "loopback_lowest":
            result = _select_loopback(interfaces, highest=False)
        elif strategy == "custom_interface":
            result = _select_custom(interfaces, custom_pattern)
        else:
            result = None
        if result:
            return result
    return None


def mark_primary(interfaces: list[dict[str, Any]], interface_name: str, address: str) -> None:
    """Set ``is_primary: True`` on the one matching entry; clear it from every other."""
    for interface in interfaces:
        for entry in _interface_addresses(interface):
            if interface.get("name") == interface_name and entry.get("address") == address:
                entry["is_primary"] = True
            else:
                entry.pop("is_primary", None)
