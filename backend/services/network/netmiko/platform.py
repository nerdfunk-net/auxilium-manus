"""Map workflow device platform / network_driver values to Netmiko device types."""

from __future__ import annotations

import re

from netmiko.ssh_dispatcher import CLASS_MAPPER

from models.failure import FailureInfo

# Exact aliases only (after lower-casing and turning spaces/hyphens into underscores). There is no
# substring matching: ``cisco_iosxr`` used to land on ``cisco_ios`` and ``hpe_aruba_aoscx`` on
# ``hp_comware`` (C2-03).
_PLATFORM_MAP: dict[str, str] = {
    "ios": "cisco_ios",
    "cisco_ios": "cisco_ios",
    "cisco": "cisco_ios",
    "nxos": "cisco_nxos",
    "nx_os": "cisco_nxos",
    "cisco_nxos": "cisco_nxos",
    "cisco_nx_os": "cisco_nxos",
    "asa": "cisco_asa",
    "cisco_asa": "cisco_asa",
    "xe": "cisco_xe",
    "iosxe": "cisco_xe",
    "ios_xe": "cisco_xe",
    "cisco_xe": "cisco_xe",
    "cisco_ios_xe": "cisco_xe",
    "cisco_iosxe": "cisco_xe",
    "xr": "cisco_xr",
    "iosxr": "cisco_xr",
    "ios_xr": "cisco_xr",
    "cisco_xr": "cisco_xr",
    "cisco_ios_xr": "cisco_xr",
    "cisco_iosxr": "cisco_xr",
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

# Netmiko's own driver names (416 of them); the automatic path never picks telnet or serial
# transports (an explicit override stays possible).
_NETMIKO_TYPES = frozenset(key for key in CLASS_MAPPER if not key.endswith(("_telnet", "_serial")))


class UnsupportedPlatformError(ValueError):
    """No SSH driver is known for the device's platform."""

    def __init__(self, network_driver: str | None, platform: str | None) -> None:
        super().__init__(
            "No SSH driver is known for this device's platform; set a driver override on the step"
        )
        self.failure = FailureInfo(
            phase="connect", kind="unsupported_platform", hint="check_platform"
        )


def _normalize(value: str) -> str:
    return re.sub(r"[\s\-]+", "_", value.strip().lower())


def resolve_netmiko_device_type(
    *,
    network_driver: str | None,
    platform: str | None = None,
) -> str:
    """Return a Netmiko ``device_type`` string for the given device metadata.

    Raises ``UnsupportedPlatformError`` when neither value names a known platform: guessing a
    driver would configure a device with the wrong command set.
    """
    for candidate in (network_driver, platform):
        if not candidate:
            continue
        key = _normalize(candidate)
        if key in _PLATFORM_MAP:
            return _PLATFORM_MAP[key]
        if key in _NETMIKO_TYPES:
            return key
    raise UnsupportedPlatformError(network_driver, platform)


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
