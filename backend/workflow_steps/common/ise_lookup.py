"""Shared Cisco ISE lookup helpers used by ISE-backed workflow steps.

Pagination and per-device detail resolution are identical regardless of which
ISE list endpoint produced the summaries (devices, devices-by-group, or a
filtered device list) — this module is the single place that logic lives so
`get-ise-devices` and `get-ise-tacacs-key` don't duplicate it.
"""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from services.ise.common.exceptions import ISENotFoundError
from services.ise.network_device_service import ISENetworkDeviceService

logger = logging.getLogger(__name__)


async def paginate_ise_summaries(
    fetch_page: Callable[[int], Awaitable[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Collect every ``resources`` entry from a paginated ISE SearchResult."""
    summaries: list[dict[str, Any]] = []
    page = 1
    while True:
        result = await fetch_page(page)
        search_result = result.get("SearchResult", {})
        summaries.extend(search_result.get("resources", []))
        if not search_result.get("nextPage"):
            break
        page += 1
    return summaries


async def fetch_ise_device_details(
    device_service: ISENetworkDeviceService, summaries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Resolve list summaries (id/name only) into full device detail dicts.

    ISE's list endpoints only return id/name/description — NetworkDeviceIPList
    and tacacsSettings are only present on the per-device detail fetch.
    """
    details: list[dict[str, Any]] = []
    for summary in summaries:
        device_id = summary.get("id")
        if not device_id:
            continue
        try:
            result = await device_service.get_device(device_id)
        except ISENotFoundError:
            logger.warning(
                "ise-lookup: device id '%s' disappeared before detail fetch, skipping",
                device_id,
            )
            continue
        detail = result.get("NetworkDevice")
        if detail:
            details.append(detail)
    return details


def extract_tacacs_shared_secret(detail: dict[str, Any]) -> str | None:
    """Read ``tacacsSettings.sharedSecret`` off a raw ISE NetworkDevice detail dict."""
    tacacs_settings = detail.get("tacacsSettings")
    if isinstance(tacacs_settings, dict):
        shared_secret = tacacs_settings.get("sharedSecret")
        if shared_secret:
            return str(shared_secret)
    return None


def _parse_range(raw: str) -> tuple[ipaddress.IPv4Address, ipaddress.IPv4Address] | None:
    """Parse an ISE IP *range* entry, e.g. ``"192.168.178.1-254"`` (only the
    last octet varies) or ``"192.168.178.1-192.168.178.254"`` (full end IP)."""
    start_part, _, end_part = raw.partition("-")
    start_part = start_part.strip()
    end_part = end_part.strip()
    try:
        start = ipaddress.IPv4Address(start_part)
    except ValueError:
        return None

    if "." in end_part:
        try:
            end = ipaddress.IPv4Address(end_part)
        except ValueError:
            return None
    else:
        try:
            last_octet = int(end_part)
        except ValueError:
            return None
        if not 0 <= last_octet <= 255:
            return None
        octets = str(start).split(".")
        octets[-1] = str(last_octet)
        try:
            end = ipaddress.IPv4Address(".".join(octets))
        except ValueError:
            return None

    if int(end) < int(start):
        start, end = end, start
    return start, end


def _wildcard_matches(pattern: str, target: ipaddress.IPv4Address) -> bool:
    """Match an ISE wildcard entry, e.g. ``"192.168.178.*"`` or ``"10.*.*.*"``."""
    pattern_octets = pattern.split(".")
    if len(pattern_octets) != 4:
        return False
    target_octets = str(target).split(".")
    for pattern_octet, target_octet in zip(pattern_octets, target_octets, strict=True):
        if pattern_octet != "*" and pattern_octet != target_octet:
            return False
    return True


def ip_entry_matches(entry: dict[str, Any], target: ipaddress.IPv4Address) -> bool:
    """Check whether *target* falls within one ``NetworkDeviceIPList`` entry.

    ISE represents a NAD's IP coverage in several shapes, and ``mask`` is not
    always meaningful — a range or wildcard entry still reports ``mask: 32``
    as a filler value, not a real netmask:

    - a single host address (``mask`` 32 or absent)
    - a CIDR network (``ipaddress`` = network address, ``mask`` 0-31)
    - a start-end *range* string, e.g. ``"192.168.178.1-254"``
    - a wildcard string, e.g. ``"192.168.178.*"``
    """
    raw = str(entry.get("ipaddress") or "").strip()
    if not raw:
        return False

    if "*" in raw:
        return _wildcard_matches(raw, target)

    if "-" in raw:
        bounds = _parse_range(raw)
        if bounds is None:
            return False
        start, end = bounds
        return start <= target <= end

    if "/" in raw:
        try:
            network = ipaddress.ip_network(raw, strict=False)
        except ValueError:
            return False
        return target in network

    mask = entry.get("mask")
    try:
        network = ipaddress.ip_network(f"{raw}/{mask if mask is not None else 32}", strict=False)
    except ValueError:
        return False
    return target in network


def device_ip_list_matches(detail: dict[str, Any], target: ipaddress.IPv4Address) -> bool:
    """True if any ``NetworkDeviceIPList`` entry on *detail* contains *target*."""
    for entry in detail.get("NetworkDeviceIPList") or []:
        if ip_entry_matches(entry, target):
            return True
    return False
