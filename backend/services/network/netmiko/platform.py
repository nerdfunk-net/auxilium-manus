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


def resolve_netmiko_device_type(
    *,
    network_driver: str | None,
    platform: str | None = None,
) -> str:
    """Return a Netmiko ``device_type`` string for the given device metadata."""
    candidates = [network_driver, platform]
    for candidate in candidates:
        if not candidate:
            continue
        normalized = candidate.strip().lower()
        if normalized in _PLATFORM_MAP:
            return _PLATFORM_MAP[normalized]
        for key, value in _PLATFORM_MAP.items():
            if key in normalized:
                return value

    logger.warning(
        "Unknown platform/network_driver (%r / %r); defaulting to cisco_ios",
        network_driver,
        platform,
    )
    return "cisco_ios"


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
