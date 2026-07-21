"""Shared Cisco config parsing helpers.

Used by the `parse-cisco-config` step executor and by the ad-hoc
`POST /netmiko/get-configs` template-editor preview endpoint, so both paths
parse device configuration identically.
"""

from __future__ import annotations

from typing import Any

from cisco_config_parser import ConfigParser

# cisco-config-parser's Parser._normalize_platform() lower-cases and looks
# this up in its own PLATFORM_ALIASES map, so passing "IOS"/"NXOS"/"XR"
# directly (rather than the Netmiko-style driver name) is accepted.
NETWORK_DRIVER_PLATFORM_HINTS = {
    "cisco_ios": "IOS",
    "cisco_xe": "IOS",
    "cisco_ios_xe": "IOS",
    "cisco_nxos": "NXOS",
    "cisco_xr": "XR",
    "cisco_ios_xr": "XR",
}


def platform_hint_for_network_driver(network_driver: str | None) -> str | None:
    return NETWORK_DRIVER_PLATFORM_HINTS.get((network_driver or "").strip().lower())


def parse_cisco_config_text(content: str, platform_hint: str | None) -> dict[str, Any]:
    return ConfigParser(content, platform=platform_hint).parse()
