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

# `devices(primary_ip4:)` is not a GraphQL argument in Nautobot, and
# `devices(ip_addresses:)` matches an IP on *any* interface. Look the IP up
# instead and follow `primary_ip4_for`. A bare host in `address` matches the
# stored IP whatever its mask (Nautobot's `net_in`), so callers strip the mask.
_PRIMARY_IP4_QUERY = """
query DeviceByPrimaryIp4($address: [String]) {
  ip_addresses(address: $address) {
    address
    primary_ip4_for {
      id
      name
    }
  }
}
"""

_DEVICES_BY_INTERFACE_IP_QUERY = """
query DeviceByInterfaceIp($address: [String]) {
  ip_addresses(address: $address) {
    interface_assignments {
      interface {
        device {
          id
          name
        }
      }
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


def strip_ip_mask(ip_address: str) -> str:
    """Return the bare host address, dropping any `/prefix` and whitespace."""
    return ip_address.strip().split("/")[0]


async def find_device_id_by_name(
    *,
    nautobot_service: NautobotService,
    credentials: NautobotCredentials,
    name: str,
    case_insensitive: bool = False,
) -> str | None:
    """Look a Nautobot device up by name only. `case_insensitive` uses `name__ie`."""
    query = _DEVICES_BY_NAME_IE_QUERY if case_insensitive else _DEVICES_BY_NAME_QUERY
    response = await nautobot_service.graphql_query(query, {"names": [name]}, credentials)
    devices = (response.get("data") or {}).get("devices") or []
    if case_insensitive:
        resolved = devices[0] if devices else None
    else:
        exact = next((item for item in devices if item.get("name") == name), None)
        resolved = exact or (devices[0] if devices else None)
    if resolved and resolved.get("id"):
        logger.info("Resolved Nautobot device by name name=%s id=%s", name, resolved["id"])
        return str(resolved["id"])
    return None


async def find_device_id_by_primary_ip(
    *,
    nautobot_service: NautobotService,
    credentials: NautobotCredentials,
    ip_address: str,
) -> str | None:
    """Find the device whose primary IPv4 is `ip_address` (mask ignored).

    An address that exists but is only assigned to an interface (not set as a
    device's primary) does not match — use `find_device_id_by_interface_ip`.
    """
    address = strip_ip_mask(ip_address)
    response = await nautobot_service.graphql_query(
        _PRIMARY_IP4_QUERY, {"address": [address]}, credentials
    )
    if response.get("errors"):
        logger.warning(
            "Nautobot primary-IP lookup returned GraphQL errors ip=%s errors=%s",
            address,
            response["errors"],
        )
    for ip_obj in (response.get("data") or {}).get("ip_addresses") or []:
        resolved_id = _first_device_id(ip_obj.get("primary_ip4_for") or [])
        if resolved_id:
            logger.info("Resolved Nautobot device by primary ip=%s id=%s", address, resolved_id)
            return resolved_id
    return None


async def find_device_id_by_interface_ip(
    *,
    nautobot_service: NautobotService,
    credentials: NautobotCredentials,
    ip_address: str,
) -> str | None:
    """Find a device with `ip_address` assigned to any of its interfaces."""
    address = strip_ip_mask(ip_address)
    response = await nautobot_service.graphql_query(
        _DEVICES_BY_INTERFACE_IP_QUERY, {"address": [address]}, credentials
    )
    for ip_obj in (response.get("data") or {}).get("ip_addresses") or []:
        for assignment in ip_obj.get("interface_assignments") or []:
            interface = assignment.get("interface") or {}
            device = interface.get("device") or {}
            if device.get("id"):
                logger.info(
                    "Resolved Nautobot device by interface ip=%s id=%s", address, device["id"]
                )
                return str(device["id"])
    return None


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
        resolved_id = await find_device_id_by_name(
            nautobot_service=nautobot_service,
            credentials=credentials,
            name=device.name,
            case_insensitive=case_insensitive,
        )
        if resolved_id:
            return resolved_id

    if device.primary_ip4:
        return await find_device_id_by_primary_ip(
            nautobot_service=nautobot_service,
            credentials=credentials,
            ip_address=device.primary_ip4,
        )

    return None
