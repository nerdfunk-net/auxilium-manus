"""Which hosts this agent may talk to or hand to the workflow (pure functions plus one resolver).

The same rules the app applies (``backend/core/safe_hosts.py``): no link-local address (the cloud
metadata address is 169.254.169.254), no unspecified or multicast address, no metadata host name.
Loopback is allowed for the Nautobot URL (Nautobot may run on this host) but never as a device.
IPv4-mapped IPv6 addresses are unwrapped first (``::ffff:169.254.169.254``).
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from typing import Any

from aiohttp.abc import AbstractResolver
from aiohttp.resolver import ThreadedResolver

logger = logging.getLogger(__name__)

BLOCKED_NAMES = frozenset({"metadata.google.internal", "metadata.google.com"})
MAX_NAME_CHARS = 253
_HOSTNAME = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?$")


def address_blocked(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address, *, loopback: bool
) -> bool:
    """True when *address* is never an acceptable target; ``loopback`` says whether it is."""
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if address.is_unspecified or address.is_multicast or address.is_link_local:
        return True
    return address.is_loopback and loopback


def host_blocked(host: str, *, loopback_blocked: bool) -> bool:
    """True when the host name or address literal *host* is not acceptable."""
    lowered = host.strip().lower().rstrip(".")
    if lowered in BLOCKED_NAMES:
        return True
    try:
        literal = ipaddress.ip_address(lowered.strip("[]"))
    except ValueError:
        return False
    return address_blocked(literal, loopback=loopback_blocked)


def usable_device_name(name: str) -> bool:
    """A name the *Get from Agent* step accepts: a plain host name, not a blocked host or address.

    A PTR record is controlled by whoever runs the DNS zone; one odd record must not fail the
    whole inventory, so the caller falls back to the IP address.
    """
    if not name or len(name) > MAX_NAME_CHARS or not _HOSTNAME.fullmatch(name):
        return False
    return not host_blocked(name, loopback_blocked=True)


class SafeResolver(AbstractResolver):
    """Resolves like aiohttp's default, but never hands back a blocked address.

    The check happens when the connection is made, so a name whose record points at a link-local
    or metadata address (or changes to one later) cannot receive the Nautobot token.
    """

    def __init__(self) -> None:
        self._inner = ThreadedResolver()

    async def resolve(
        self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_INET
    ) -> list[dict[str, Any]]:
        found = await self._inner.resolve(host, port, family)
        allowed = [
            entry
            for entry in found
            if not address_blocked(ipaddress.ip_address(entry["host"]), loopback=False)
        ]
        if not allowed:
            logger.warning("refusing to connect: the host name resolves only to blocked addresses")
            raise OSError(
                "the host resolves only to link-local, multicast or unspecified addresses"
            )
        return allowed  # type: ignore[return-value]

    async def close(self) -> None:
        await self._inner.close()
