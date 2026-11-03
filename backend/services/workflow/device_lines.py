"""Device lines for a workflow's Get from User step, and finding the steps that read them.

Get from User takes its devices from a text run input, one ``name,ip[,network_driver]`` line per
device. Both callers that hand devices to a workflow (the ``start-workflow`` step and the Ask the
Net released-workflow start) build those lines here, so the format has one definition.
"""

from __future__ import annotations

import ipaddress
from typing import Any

from services.nautobot.common.validators import validate_ip_address
from services.network.netmiko.platform import UnsupportedPlatformError, resolve_netmiko_device_type

DEVICE_INPUT_STEP_KIND = "get-from-user"


def forwardable_driver(network_driver: str | None, platform: str | None) -> str:
    """The canonical Netmiko type SSH steps would use, or "" when there is none.

    A value Netmiko rejects is not forwarded: it would make Get from User refuse the device.
    """
    try:
        return resolve_netmiko_device_type(
            network_driver=(network_driver or "").strip() or None,
            platform=(platform or "").strip() or None,
        )
    except UnsupportedPlatformError:
        return ""


def device_line(
    *, name: str | None, ip: str | None, network_driver: str | None, platform: str | None
) -> str | None:
    """One ``name,ip[,driver]`` line, or None without a usable identity.

    A name that would break the line format (a comma or a line break) is left out; the bare IP
    stands in for it. Without a resolvable driver the started workflow's default applies.
    """
    clean_name = (name or "").strip()
    if not clean_name or "," in clean_name or len(clean_name.splitlines()) != 1:
        clean_name = ""
    clean_ip = (ip or "").strip()
    if clean_ip and not validate_ip_address(clean_ip):
        clean_ip = ""
    if not clean_name and not clean_ip:
        return None
    driver = forwardable_driver(network_driver, platform)
    if driver:
        return f"{clean_name},{clean_ip},{driver}"
    if clean_name and clean_ip:
        return f"{clean_name},{clean_ip}"
    return clean_name or clean_ip


def parse_ipv4_literal(value: str) -> str | None:
    """The canonical dotted-quad when ``value`` is exactly one IPv4 address, else None.

    Strict on purpose: no host names, CIDR, ranges, whitespace, commas or line breaks, so the
    result can never add a second line to a device list.
    """
    if not isinstance(value, str) or value != value.strip():
        return None
    if not value or not all(c in "0123456789." for c in value):
        return None
    try:
        return str(ipaddress.IPv4Address(value))
    except ValueError:
        return None


def enabled_device_input_readers(nodes: list[Any], devices_input: str) -> list[str]:
    """Ids of the enabled Get from User steps whose ``device_param`` is ``devices_input``."""
    return [
        str(node["id"])
        for node in nodes
        if isinstance(node, dict)
        and node.get("id") is not None
        and (node.get("data") or {}).get("disabled") is not True
        and (node.get("data") or {}).get("kind") == DEVICE_INPUT_STEP_KIND
        and ((node.get("data") or {}).get("pluginConfig") or {}).get("device_param")
        == devices_input
    ]
