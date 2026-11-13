"""Management address of a discovered device, read from Nautobot.

CDP reports an *interface* address of a neighbour. Where SSH is allowed only to the
management or loopback address, that address cannot be logged into. Two lookups, in order:

1. the neighbour's **name** -> the device -> its ``primary_ip4``;
2. when that finds nothing usable, the reported **interface address** -> the device that owns
   it (name and ``primary_ip4``).

An answer is used only when it is unambiguous: a name or address that matches several devices
is never guessed. The address that comes back is only a candidate: the crawler still checks it
against the permitted prefixes and the host policy before any login. Any Nautobot failure
leaves the neighbour as CDP reported it (``unavailable`` tells the step summary).
"""

from __future__ import annotations

import ipaddress
import logging
from dataclasses import replace
from typing import Any

from nautobot_read.client import GraphQLClient, NautobotError
from sqlalchemy.orm import Session

import service_factory
from services.nautobot.graphql_client import NautobotServiceClient
from workflow_steps.common.nautobot_source import resolve_nautobot_credentials
from workflow_steps.discover_network.parsing import Neighbor
from workflow_steps.discover_network.scope import STEP_ID

logger = logging.getLogger(__name__)

SOURCE_NAME = "nautobot_name"
SOURCE_IP = "nautobot_ip"

_DEVICE_SELECTION = "id name primary_ip4 { address }"
_IP_SELECTION = "address interfaces { device { id name primary_ip4 { address } } }"
# How a name is matched, until one filter finds something: exact, ignoring case, and as the
# start of a full name (``sw2`` finds ``sw2.example.com``). Same order as the library's lookup.
_NAME_FILTERS = (("name", ""), ("name__ie", ""), ("name__isw", "."))
_MAX_ROWS = 6  # enough to see that a match is ambiguous


def _primary_ip(device: dict[str, Any]) -> str | None:
    address = (device.get("primary_ip4") or {}).get("address")
    if not isinstance(address, str):
        return None
    try:
        parsed = ipaddress.ip_interface(address.strip())
    except ValueError:
        return None
    return str(parsed.ip) if isinstance(parsed.ip, ipaddress.IPv4Address) else None


class ManagementIpLookup:
    """Resolves neighbours through one Nautobot client; results are cached for the run."""

    def __init__(self, client: GraphQLClient | Any) -> None:
        self._client = client
        self._cache: dict[tuple[str, str | None], tuple[str, str, str] | None] = {}
        self.unavailable = False

    async def resolve(self, neighbor: Neighbor) -> Neighbor:
        """The neighbour with its management address, or unchanged when none was found."""
        key = (neighbor.name.lower(), neighbor.ip)
        if key not in self._cache:
            try:
                self._cache[key] = await self._lookup(neighbor)
            except NautobotError:
                # The client logged the code; the message is a fixed sentence.
                self.unavailable = True
                logger.info("discover-network: Nautobot lookup failed; using the CDP address")
                self._cache[key] = None
        found = self._cache[key]
        if found is None:
            return neighbor
        ip, name, source = found
        return replace(neighbor, ip=ip, name=name, reported_ip=neighbor.ip, ip_source=source)

    async def _lookup(self, neighbor: Neighbor) -> tuple[str, str, str] | None:
        by_name = await self._by_name(neighbor.name)
        if by_name is not None:
            return by_name, neighbor.name, SOURCE_NAME
        if neighbor.ip is None:
            return None
        by_ip = await self._by_interface_ip(neighbor.ip)
        if by_ip is None:
            return None
        return by_ip[1], by_ip[0], SOURCE_IP

    async def _by_name(self, name: str) -> str | None:
        candidates = [name]
        first_label = name.split(".", 1)[0]
        if first_label and first_label != name:
            candidates.append(first_label)
        for candidate in candidates:
            for filter_name, suffix in _NAME_FILTERS:
                if candidate is not name and filter_name != "name__ie":
                    continue  # the first label is only matched as a whole name
                page = await self._client.list_page(
                    "devices", _DEVICE_SELECTION, {filter_name: [candidate + suffix]},
                    limit=_MAX_ROWS, offset=0,
                )  # fmt: skip
                if len(page.items) == 1:
                    return _primary_ip(page.items[0])
                if page.items:
                    return None  # several devices: never guess
        return None

    async def _by_interface_ip(self, ip: str) -> tuple[str, str] | None:
        page = await self._client.list_page(
            "ip_addresses", _IP_SELECTION, {"address": [ip]}, limit=_MAX_ROWS, offset=0
        )
        devices: dict[str, dict[str, Any]] = {}
        for row in page.items:
            for interface in row.get("interfaces") or []:
                owner = interface.get("device")
                if owner and owner.get("name"):
                    devices[owner["id"] if owner.get("id") else owner["name"]] = owner
        if len(devices) != 1:
            return None
        owner = next(iter(devices.values()))
        primary = _primary_ip(owner)
        return (owner["name"], primary) if primary else None


def build_management_ip_lookup(db: Session, source_id: str) -> ManagementIpLookup:
    """A lookup on the Nautobot source ``source_id``; ``ValueError`` when the source is unusable.

    Not strict: a list that arrives next to a non-fatal GraphQL error (a nested field the token
    may not read) is still used, as in ``get-virtual-chassis``.
    """
    credentials = resolve_nautobot_credentials(db, source_id, step_id=STEP_ID)
    service = service_factory.get_nautobot_app_service()
    return ManagementIpLookup(NautobotServiceClient(service, credentials, strict=False))
