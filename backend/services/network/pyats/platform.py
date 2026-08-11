"""Map workflow device platform / network_driver values to Genie/pyATS ``os`` strings.

Mirrors ``services/network/netmiko/platform.py``'s structure, but the target
vocabulary differs: Netmiko's ``device_type`` (``cisco_ios``, ``cisco_xe``, ...)
is not the same as Genie/pyATS's ``os`` (``ios``, ``iosxe``, ...).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_PLATFORM_MAP: dict[str, str] = {
    "ios": "ios",
    "cisco_ios": "ios",
    "iosxe": "iosxe",
    "cisco_xe": "iosxe",
    "cisco_ios_xe": "iosxe",
    "xe": "iosxe",
    "nxos": "nxos",
    "cisco_nxos": "nxos",
    "iosxr": "iosxr",
    "cisco_xr": "iosxr",
    "cisco_ios_xr": "iosxr",
    "xr": "iosxr",
    "asa": "asa",
    "cisco_asa": "asa",
    "junos": "junos",
    "juniper": "junos",
    "juniper_junos": "junos",
    "eos": "eos",
    "arista": "eos",
    "arista_eos": "eos",
}


def resolve_pyats_os(
    *,
    network_driver: str | None,
    platform: str | None = None,
    override: str | None = None,
) -> str:
    """Return a Genie/pyATS ``os`` string for the given device metadata.

    Honors an explicit step-level ``override`` first (same precedence as
    ``resolve_connection_device_type`` in the Netmiko sibling module), then
    falls back to matching ``network_driver``/``platform`` against
    ``_PLATFORM_MAP``, defaulting to ``"ios"`` when nothing matches.
    """
    if override:
        normalized_override = override.strip().lower()
        if normalized_override:
            if normalized_override in _PLATFORM_MAP:
                return _PLATFORM_MAP[normalized_override]
            return normalized_override

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
        "Unknown platform/network_driver (%r / %r); defaulting to ios",
        network_driver,
        platform,
    )
    return "ios"
