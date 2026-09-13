"""Resolve a workflow DeviceContext to a Nautobot device UUID."""

from __future__ import annotations

import logging
import re
from typing import Any

from models.workflow_context import DeviceContext
from services.nautobot.client import NautobotService
from services.nautobot.credentials import NautobotCredentials

logger = logging.getLogger(__name__)

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

_DEVICES_BY_NAME_QUERY = """
query DevicesByName($names: [String]) {
  devices(name: $names) {
    id
    name
  }
}
"""

_DEVICES_BY_NAME_IE_QUERY = """
query DevicesByNameCaseInsensitive($names: [String]) {
  devices(name__ie: $names) {
    id
    name
  }
}
"""

_DEVICES_BY_IP_QUERY = """
query DevicesByPrimaryIp($addresses: [String]) {
  devices(primary_ip4: $addresses) {
    id
    name
    primary_ip4 {
      address
    }
  }
}
"""


def _is_nautobot_uuid(device_id: str) -> bool:
    return bool(_UUID_RE.match(device_id))


def _first_device_id(devices: list[dict[str, Any]]) -> str | None:
    if not devices:
        return None
    device_id = devices[0].get("id")
    return str(device_id) if device_id else None


async def resolve_nautobot_device_id(
    *,
    nautobot_service: NautobotService,
    credentials: NautobotCredentials,
    device: DeviceContext,
    case_insensitive: bool = False,
) -> str | None:
    """Map a workflow device to a Nautobot UUID.

    Only a device whose `source` is already "nautobot" gets its id trusted
    as-is (and only when it's UUID-shaped). Every other source — including
    ones whose own id happens to be UUID-shaped, like ISE's device GUIDs —
    falls through to resolution by name, then by primary IPv4 address, since
    a foreign UUID has no meaning in Nautobot's id space.

    `case_insensitive` switches the name lookup to Nautobot's `name__ie`
    filter (case-insensitive exact match) — needed for sources such as
    Batfish that normalize device names to lowercase.
    """
    if device.source == "nautobot" and _is_nautobot_uuid(device.id):
        return device.id

    if device.name:
        query = _DEVICES_BY_NAME_IE_QUERY if case_insensitive else _DEVICES_BY_NAME_QUERY
        response = await nautobot_service.graphql_query(
            query,
            {"names": [device.name]},
            credentials,
        )
        devices = (response.get("data") or {}).get("devices") or []
        if case_insensitive:
            resolved = devices[0] if devices else None
        else:
            exact = next((item for item in devices if item.get("name") == device.name), None)
            resolved = exact or (devices[0] if devices else None)
        if resolved and resolved.get("id"):
            logger.info(
                "Resolved Nautobot device by name name=%s id=%s",
                device.name,
                resolved["id"],
            )
            return str(resolved["id"])

    if device.primary_ip4:
        address = device.primary_ip4 if "/" in device.primary_ip4 else f"{device.primary_ip4}/32"
        response = await nautobot_service.graphql_query(
            _DEVICES_BY_IP_QUERY,
            {"addresses": [address]},
            credentials,
        )
        devices = (response.get("data") or {}).get("devices") or []
        resolved_id = _first_device_id(devices)
        if resolved_id:
            logger.info(
                "Resolved Nautobot device by primary_ip4 address=%s id=%s",
                address,
                resolved_id,
            )
            return resolved_id

    return None
