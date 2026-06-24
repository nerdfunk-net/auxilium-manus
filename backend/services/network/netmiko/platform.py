"""Map workflow device platform / network_driver values to Netmiko device types."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_PLATFORM_MAP: dict[str, str] = {
    "ios": "cisco_ios",
    "cisco_ios": "cisco_ios",
    "nxos": "cisco_nxos",
    "cisco_nxos": "cisco_nxos",
    "asa": "cisco_asa",
    "cisco_asa": "cisco_asa",
    "xe": "cisco_xe",
    "cisco_xe": "cisco_xe",
    "xr": "cisco_xr",
    "cisco_xr": "cisco_xr",
    "junos": "juniper_junos",
    "juniper": "juniper_junos",
    "juniper_junos": "juniper_junos",
    "arista": "arista_eos",
    "eos": "arista_eos",
    "arista_eos": "arista_eos",
    "hp": "hp_comware",
    "comware": "hp_comware",
    "hp_comware": "hp_comware",
}


def resolve_connection_device_type(
    *,
    network_driver: str | None,
    platform: str | None = None,
    override: str | None = None,
) -> str:
    """Resolve Netmiko device type, honoring an explicit step-level override."""
    if override:
        normalized = override.strip().lower()
        if normalized:
            if normalized in _PLATFORM_MAP:
                return _PLATFORM_MAP[normalized]
            return normalized
    return resolve_netmiko_device_type(network_driver=network_driver, platform=platform)
