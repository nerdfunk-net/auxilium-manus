"""Read-only checks run before a device is created in Nautobot.

``DeviceCreationService`` POSTs the device first and creates IPs and interfaces afterwards, so a
problem found only then leaves a device without its IPs and interfaces. These checks look for the
avoidable problems up front: an interface without a ``type``, an IP address that does not parse,
a namespace that does not exist, and (with ``add_prefix`` off) an IP without a parent prefix.

A lookup that itself fails (Nautobot unreachable) is logged and skipped, never reported as a
problem of the request.
"""

from __future__ import annotations

import ipaddress
import logging
from typing import Any

from services.nautobot.api_protocol import NautobotApi
from services.nautobot.common.rest import rest_query
from services.nautobot.devices.common import DeviceCommonService
from services.nautobot.devices.interface_workflow.payload import (
    ip_namespace,
    normalize_interface_ip_list,
)

logger = logging.getLogger(__name__)


def interface_type_errors(interfaces: list[dict[str, Any]]) -> list[str]:
    """One message per named interface that has no ``type`` (it would be skipped later)."""
    errors: list[str] = []
    for interface in interfaces:
        name = str(interface.get("name") or "").strip()
        if name and not str(interface.get("type") or "").strip():
            errors.append(f"Interface {name}: type is required")
    return errors


async def _count(nautobot: NautobotApi, endpoint: str) -> int | None:
    """Result count of a lookup, or ``None`` when the lookup failed."""
    try:
        result = await nautobot.rest_request(endpoint)
    except Exception as exc:
        logger.warning("Pre-flight lookup failed (%s): %s", endpoint.split("?", 1)[0], exc)
        return None
    return int(result.get("count", 0)) if isinstance(result, dict) else 0


async def _resolve_namespaces(
    common: DeviceCommonService, names: list[str], errors: list[str]
) -> dict[str, str]:
    """Map each namespace name to its id; an unknown one is reported once."""
    resolved: dict[str, str] = {}
    for name in names:
        try:
            resolved[name] = await common.resolve_namespace_id(name)
        except ValueError:
            errors.append(f"Namespace '{name}' not found in Nautobot")
        except Exception as exc:
            logger.warning("Pre-flight: could not resolve namespace %r: %s", name, exc)
    return resolved


async def _missing_prefix_error(
    nautobot: NautobotApi,
    *,
    address: ipaddress.IPv4Interface | ipaddress.IPv6Interface,
    text: str,
    namespace: str,
    namespace_id: str,
    interface_name: str,
) -> str | None:
    """An error when a new IP has no parent prefix in the namespace, else ``None``."""
    existing = await _count(
        nautobot,
        "ipam/ip-addresses/?" + rest_query(address=text, namespace=namespace_id, format="json"),
    )
    if existing is None or existing > 0:
        return None
    # Nautobot picks an IP's parent prefix by containment of its host address; the mask plays no
    # part. Any prefix containing the host is a valid parent, so the host is queried, not the
    # network (a /25 containing 10.0.0.5 parents 10.0.0.5/24).
    prefixes = await _count(
        nautobot,
        "ipam/prefixes/?"
        + rest_query(contains=str(address.ip), namespace=namespace_id, limit=1, format="json"),
    )
    if prefixes != 0:
        return None
    return (
        f"No parent prefix for {text} in namespace '{namespace}' (interface {interface_name}) "
        "- create it or enable 'add_prefix'"
    )


def _parse_ip_entries(
    interfaces: list[dict[str, Any]], errors: list[str]
) -> list[tuple[str, str, ipaddress.IPv4Interface | ipaddress.IPv6Interface, str]]:
    """``(interface name, address text, parsed address, namespace)`` for every valid IP."""
    entries = []
    for interface in interfaces:
        name = str(interface.get("name") or "").strip()
        for ip_data in normalize_interface_ip_list(interface):
            text = str(ip_data.get("address") or "").strip()
            if not text:
                continue
            try:
                parsed = ipaddress.ip_interface(text)
            except ValueError:
                errors.append(f"Interface {name}: '{text}' is not a valid IP address")
                continue
            entries.append((name, text, parsed, ip_namespace(interface, ip_data)))
    return entries


async def interface_ip_errors(
    *,
    nautobot: NautobotApi,
    common: DeviceCommonService,
    interfaces: list[dict[str, Any]],
    add_prefix: bool,
) -> list[str]:
    """Problems with the IP addresses of ``interfaces`` (parse, namespace, parent prefix)."""
    errors: list[str] = []
    entries = _parse_ip_entries(interfaces, errors)
    namespace_ids = await _resolve_namespaces(
        common, list(dict.fromkeys(namespace for *_, namespace in entries)), errors
    )
    if add_prefix:
        return errors  # a missing prefix is created when the IP is added
    checked: set[tuple[str, str]] = set()
    for name, text, parsed, namespace in entries:
        namespace_id = namespace_ids.get(namespace)
        if namespace_id is None or (namespace, text) in checked:
            continue
        checked.add((namespace, text))
        error = await _missing_prefix_error(
            nautobot,
            address=parsed,
            text=text,
            namespace=namespace,
            namespace_id=namespace_id,
            interface_name=name,
        )
        if error:
            errors.append(error)
    return errors


async def preflight_errors(
    *,
    nautobot: NautobotApi,
    common: DeviceCommonService,
    interfaces: list[dict[str, Any]],
    add_prefix: bool,
) -> list[str]:
    """All problems found before creating a device with ``interfaces`` (empty = go ahead)."""
    if not interfaces:
        return []
    return [
        *interface_type_errors(interfaces),
        *await interface_ip_errors(
            nautobot=nautobot, common=common, interfaces=interfaces, add_prefix=add_prefix
        ),
    ]
