"""CDP detail parsing for the discover-network step (pure, no I/O).

Netmiko returns the TextFSM result as a JSON string when a template matched and as the raw
device text otherwise. Everything a neighbour reports is attacker-influenced text: names and
platform strings are stripped of control characters and cut, and never used to build commands.
"""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from services.network.netmiko.output_check import find_cli_error
from workflow_steps.common.neighbor_capabilities import (
    INFRASTRUCTURE_CAPABILITIES,
    parse_capabilities,
)

CDP_COMMAND = "show cdp neighbors detail"
SUPPORTED_DEVICE_TYPES = frozenset({"cisco_ios", "cisco_xe", "cisco_nxos"})
_MAX_TEXT = 100
_MAX_SOFTWARE = 200

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_ZERO_ENTRIES = re.compile(r"total (?:cdp )?entries displayed\s*:\s*0\b", re.IGNORECASE)
_CDP_OFF = re.compile(
    r"\bcdp\b[^\n]*\bnot (?:enabled|running|active)\b|\bnot (?:enabled|running)\b[^\n]*\bcdp\b",
    re.IGNORECASE,
)
_NXOS = re.compile(r"\bnexus|\bn[2-9]k\b|\bn[2-9][0-9]{2}\b", re.IGNORECASE)
# Platforms that run IOS-XE (Catalyst 9000, ISR/ASR, CSR, Catalyst 8000), checked after NX-OS.
_XE = re.compile(
    r"\bc9[0-9]{3}|\bcatalyst ?9[0-9]{3}|\bisr\s?4|\basr\s?1|\bcsr\s?1|\bc8[0-9]{3}", re.IGNORECASE
)
_IOS = re.compile(r"\bws-c|\bcatalyst|\bc[23][0-9]{3}|\bcisco ?(?:18|28|38|29|35|37)[0-9]{2}", re.I)


class CdpStatus(StrEnum):
    OK = "ok"
    NOT_ENABLED = "not_enabled"
    NOT_SUPPORTED = "not_supported"
    UNPARSEABLE = "unparseable"


@dataclass(frozen=True)
class Neighbor:
    """One device a port saw through CDP."""

    name: str
    ip: str | None
    platform: str
    local_port: str
    remote_port: str
    capabilities: tuple[str, ...]
    # First line of the "Version" block of the detail output ("Cisco IOS Software [IOSXE], ...").
    software: str = ""
    # Set when the Nautobot lookup replaced the address: the interface address CDP reported,
    # and where the address in ``ip`` now comes from ("cdp", "nautobot_name", "nautobot_ip").
    reported_ip: str | None = None
    ip_source: str = "cdp"

    @property
    def is_infrastructure(self) -> bool:
        return bool(INFRASTRUCTURE_CAPABILITIES.intersection(self.capabilities))


@dataclass(frozen=True)
class CdpResult:
    status: CdpStatus
    neighbors: tuple[Neighbor, ...] = ()


def sanitize_text(value: object, limit: int = _MAX_TEXT) -> str:
    """Control characters removed and the text cut to *limit* characters."""
    if not isinstance(value, str):
        return ""
    return _CONTROL.sub("", value).strip()[:limit]


def _ipv4_or_none(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    return str(address) if isinstance(address, ipaddress.IPv4Address) else None


def _neighbor(row: dict[str, Any]) -> Neighbor | None:
    name = sanitize_text(row.get("neighbor_name"))
    if not name:
        return None
    return Neighbor(
        name=name,
        ip=_ipv4_or_none(row.get("mgmt_address") or row.get("management_ip")),
        platform=sanitize_text(row.get("platform")),
        local_port=sanitize_text(row.get("local_interface")),
        remote_port=sanitize_text(row.get("neighbor_interface")),
        capabilities=parse_capabilities(row.get("capabilities"), "cdp"),
        software=sanitize_text(row.get("neighbor_description"), _MAX_SOFTWARE),
    )


def classify_cdp_output(raw: str) -> CdpResult:
    """The neighbours in one ``show cdp neighbors detail`` output, or why there are none.

    Blank or unrecognised output is ``UNPARSEABLE`` and never "no neighbours": a dropped session
    prints nothing too, and an empty answer would end the walk silently.
    """
    if not raw or not raw.strip():
        return CdpResult(CdpStatus.UNPARSEABLE)
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        if find_cli_error(raw) is not None:
            return CdpResult(CdpStatus.NOT_SUPPORTED)
        if _CDP_OFF.search(raw):
            return CdpResult(CdpStatus.NOT_ENABLED)
        if _ZERO_ENTRIES.search(raw):
            return CdpResult(CdpStatus.OK)
        return CdpResult(CdpStatus.UNPARSEABLE)
    if not isinstance(decoded, list) or not all(isinstance(r, dict) for r in decoded):
        return CdpResult(CdpStatus.UNPARSEABLE)
    neighbors = tuple(n for row in decoded if (n := _neighbor(row)) is not None)
    return CdpResult(CdpStatus.OK, neighbors)


def device_type_from_platform(platform: str | None, *, override: str | None) -> str | None:
    """The Netmiko device type for a neighbour, or ``None`` when it is not supported.

    The CDP platform string decides. The override is used only when the neighbour reported no
    platform at all, and only if it names a supported device type.
    """
    text = (platform or "").strip()
    if not text:
        return override if override in SUPPORTED_DEVICE_TYPES else None
    # The model number decides: CDP platform lines often omit the vendor word ("WS-C2960-24TT-L").
    if _NXOS.search(text):
        return "cisco_nxos"
    if _XE.search(text):
        return "cisco_xe"
    if _IOS.search(text):
        return "cisco_ios"
    return None


# The software line names the operating system, which is what decides the driver. Checked in this
# order: IOS-XR and other non-supported systems first, so "IOS XR" is never read as IOS.
_SW_UNSUPPORTED = re.compile(r"\bios[ -]?xr\b|\bxrv\b|\bwireless lan controller\b", re.IGNORECASE)
_SW_NXOS = re.compile(r"\bnx-?os\b|\bnexus operating system\b", re.IGNORECASE)
_SW_XE = re.compile(r"\bios[ -]?xe\b|\[iosxe\]", re.IGNORECASE)
_SW_IOS = re.compile(r"\bcisco ios software\b", re.IGNORECASE)


def device_type_from_software(software: str | None) -> str | None:
    """The Netmiko device type named by a CDP software line, or ``None``.

    A virtual switch reports ``Platform: Linux`` but ``Cisco IOS Software [IOSXE], Linux Software
    (...)`` in its version text: the second one tells what to log in as.
    """
    text = (software or "").strip()
    if not text or _SW_UNSUPPORTED.search(text):
        return None
    if _SW_NXOS.search(text):
        return "cisco_nxos"
    if _SW_XE.search(text):
        return "cisco_xe"
    if _SW_IOS.search(text):
        return "cisco_ios"
    return None


def neighbor_device_type(neighbor: Neighbor, *, override: str | None) -> str | None:
    """The Netmiko device type to log into a neighbour as, or ``None`` when it is not supported.

    The platform string decides when it is usable; otherwise the software line; the override is
    only used for a neighbour that reported no platform and no recognisable software.
    """
    by_platform = device_type_from_platform(neighbor.platform, override=None)
    if by_platform is not None:
        return by_platform
    by_software = device_type_from_software(neighbor.software)
    if by_software is not None:
        return by_software
    return device_type_from_platform(neighbor.platform, override=override)
