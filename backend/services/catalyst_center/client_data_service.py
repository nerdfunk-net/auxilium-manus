"""Wired clients from Cisco Catalyst Center: ``POST /dna/data/api/v1/clients/query`` (read-only).

The Clients Query API is an assurance view: it returns the clients the controller saw within a time
window, not a live MAC table. One request asks for the connected wired clients of one switch
(``connectedNetworkDeviceId`` = the network-device UUID, view ``Wired``) and is paged until a
short page comes back. Built from the published ``clients/query`` contract (lowercase operators,
scalar ``eq`` values, ``ipv4Address``, ``ipv6Addresses``, ``connection.vlanId``,
``connectedNetworkDevice.*``) and unit tests; the DevNet sandbox has no clients, so it is not
verified against a real controller (paging beyond 500 clients may also need the response
``cursor``).
"""

from __future__ import annotations

import ipaddress
import time
from collections.abc import Callable
from typing import Any

from models.catalyst_center_facts import CatalystCenterClient
from services.catalyst_center.client import CatalystCenterService
from services.catalyst_center.common.coerce import text
from services.catalyst_center.common.exceptions import (
    CatalystCenterAPIError,
    CatalystCenterValidationError,
)
from services.catalyst_center.common.ids import safe_device_id
from services.catalyst_center.credentials import CatalystCenterCredentials

CLIENTS_QUERY_PATH = "/dna/data/api/v1/clients/query"
VIEWS = ["Wired"]
PAGE_LIMIT = 500
# A switch with more than 100 000 wired clients in the window is a configuration error, not data.
MAX_PAGES = 200
_MS_PER_HOUR = 3_600_000
MAX_LOOKBACK_HOURS = 168


class CatalystCenterClientDataService:
    def __init__(
        self,
        client: CatalystCenterService,
        credentials: CatalystCenterCredentials,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._client = client
        self._credentials = credentials
        self._clock = clock

    async def get_wired_clients(
        self, device_id: str, *, lookback_hours: int
    ) -> tuple[CatalystCenterClient, ...]:
        """Wired clients connected to the switch *device_id* (the controller's network-device
        UUID) that the controller saw during the last *lookback_hours*."""
        switch_id = safe_device_id(device_id)
        if not 1 <= lookback_hours <= MAX_LOOKBACK_HOURS:
            raise CatalystCenterValidationError(
                f"lookback_hours must be between 1 and {MAX_LOOKBACK_HOURS}"
            )
        end_ms = int(self._clock() * 1000)
        start_ms = end_ms - lookback_hours * _MS_PER_HOUR
        clients: list[CatalystCenterClient] = []
        for page in range(MAX_PAGES):
            payload = await self._client.request(
                self._credentials,
                "POST",
                CLIENTS_QUERY_PATH,
                json={
                    "startTime": start_ms,
                    "endTime": end_ms,
                    "views": VIEWS,
                    # Operators are lowercase and ``eq`` takes one scalar value. Only clients that
                    # are connected now answer "where is this host": a client that left the port
                    # earlier in the window would be stored as its current location.
                    "filters": [
                        {"key": "connectedNetworkDeviceId", "operator": "eq", "value": switch_id},
                        {"key": "type", "operator": "eq", "value": "Wired"},
                        {"key": "connectionStatus", "operator": "eq", "value": "connected"},
                    ],
                    # ``offset`` is 1-based in the Data API.
                    "page": {"limit": PAGE_LIMIT, "offset": page * PAGE_LIMIT + 1},
                },
            )
            rows = payload.get("response") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                raise CatalystCenterAPIError(
                    "Catalyst Center returned an unexpected clients response",
                    code="invalid_response",
                )
            clients.extend(_normalise(row) for row in rows if isinstance(row, dict))
            if len(rows) < PAGE_LIMIT:
                return tuple(clients)
        raise CatalystCenterAPIError(
            f"Catalyst Center reports more than {MAX_PAGES * PAGE_LIMIT} clients for the device"
        )


def _valid_address(candidate: str) -> str | None:
    """A global or private host address; link-local, loopback, multicast and the like are not unique
    to one host, so a lookup of them would report every client that used them."""
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return None
    if (
        address.is_unspecified
        or address.is_loopback
        or address.is_multicast
        or address.is_link_local
        or address.is_reserved
    ):
        return None
    return str(address)


def _addresses(*values: Any) -> tuple[str, ...]:
    found: list[str] = []
    for value in values:
        for item in value if isinstance(value, list) else [value]:
            candidate = text(item)
            address = _valid_address(candidate) if candidate is not None else None
            if address is not None and address not in found:
                found.append(address)
    return tuple(found)


def _section(row: dict[str, Any], key: str) -> dict[str, Any]:
    value = row.get(key)
    return value if isinstance(value, dict) else {}


def _normalise(row: dict[str, Any]) -> CatalystCenterClient:
    """Whitelist the fields of one ``Wired`` view client (never the user it authenticated as)."""
    connection = _section(row, "connection")
    switch = _section(row, "connectedNetworkDevice")
    return CatalystCenterClient(
        mac_address=text(row.get("macAddress")) or text(row.get("id")),
        ip_addresses=_addresses(row.get("ipv4Address"), row.get("ipv6Addresses")),
        vlan=text(connection.get("vlanId")),
        port=text(switch.get("interfaceName")),
        connected_device_id=text(switch.get("connectedNetworkDeviceId")),
        connected_device_name=text(switch.get("connectedNetworkDeviceName")),
    )
