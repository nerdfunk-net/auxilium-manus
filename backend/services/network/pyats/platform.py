"""Map workflow device platform / network_driver values to Genie/pyATS ``os`` strings.

Mirrors ``services/network/netmiko/platform.py``'s structure, but the target
vocabulary differs: Netmiko's ``device_type`` (``cisco_ios``, ``cisco_xe``, ...)
is not the same as Genie/pyATS's ``os`` (``ios``, ``iosxe``, ...).
"""

from __future__ import annotations

import re

from models.failure import FailureInfo

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
    "ios_xr": "iosxr",
    "cisco_iosxr": "iosxr",
    "ios_xe": "iosxe",
    "cisco_iosxe": "iosxe",
    "nx_os": "nxos",
    "cisco_nx_os": "nxos",
    "asa": "asa",
    "cisco_asa": "asa",
    "junos": "junos",
    "juniper": "junos",
    "juniper_junos": "junos",
    "eos": "eos",
    "arista": "eos",
    "arista_eos": "eos",
}


class UnsupportedPlatformError(ValueError):
    """No Genie/pyATS ``os`` is known for the device's platform."""

    def __init__(self, network_driver: str | None, platform: str | None) -> None:
        super().__init__(
            "No pyATS os is known for this device's platform; set an os override on the step"
        )
        self.failure = FailureInfo(
            phase="connect", kind="unsupported_platform", hint="check_platform"
        )


def _normalize(value: str) -> str:
    return re.sub(r"[\s\-]+", "_", value.strip().lower())


def resolve_pyats_os(
    *,
    network_driver: str | None,
    platform: str | None = None,
    override: str | None = None,
) -> str:
    """Return a Genie/pyATS ``os`` string for the given device metadata.

    Honors an explicit step-level ``override`` first (same precedence as
    ``resolve_connection_device_type`` in the Netmiko sibling module), then matches
    ``network_driver``/``platform`` exactly against ``_PLATFORM_MAP``. Raises
    ``UnsupportedPlatformError`` when nothing matches (C4-06): guessing ``ios`` would parse a
    device with the wrong parsers.
    """
    if override:
        normalized_override = override.strip().lower()
        if normalized_override:
            if normalized_override in _PLATFORM_MAP:
                return _PLATFORM_MAP[normalized_override]
            return normalized_override

    for candidate in (network_driver, platform):
        if not candidate:
            continue
        key = _normalize(candidate)
        if key in _PLATFORM_MAP:
            return _PLATFORM_MAP[key]
    raise UnsupportedPlatformError(network_driver, platform)
