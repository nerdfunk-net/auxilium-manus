"""Pure helpers that build and normalise Nautobot interface payloads."""

from __future__ import annotations

import logging
from typing import Any

from services.nautobot.common.validators import is_valid_uuid
from services.nautobot.devices.common import DeviceCommonService

logger = logging.getLogger(__name__)


def normalize_interface_ip_list(interface: dict[str, Any]) -> list[dict[str, Any]]:
    ip_addresses = interface.get("ip_addresses", [])
    if not ip_addresses and interface.get("ip_address"):
        logger.info("Found single ip_address field, converting to array format")
        return [
            {
                "address": interface["ip_address"],
                "namespace": interface.get("namespace", "Global"),
                "ip_role": interface.get("ip_role"),
            }
        ]
    return ip_addresses


def ip_map_key(interface_name: str, ip_address: str) -> str:
    return f"{interface_name}:{ip_address}"


def normalize_interface_type(
    interface: dict[str, Any],
    warnings: list[str],
) -> str | None:
    # Nautobot interface type slugs are always lowercase (e.g. "virtual", "1000base-t")
    # Frontend may store the display name (e.g. "Virtual") — normalize to lowercase slug
    interface_type = (interface.get("type") or "").strip().lower()
    if not interface_type:
        warnings.append(
            f"Interface {interface['name']}: 'type' is required but was not provided — skipping"
        )
        logger.warning("Interface '%s' has no type set, skipping creation", interface["name"])
        return None
    return interface_type


def build_interface_payload(
    *,
    device_id: str,
    interface: dict[str, Any],
    interface_type: str,
    interface_status_id: str,
    untagged_vlan_id: str | None,
    tagged_vlan_ids: list[str],
) -> dict[str, Any]:
    interface_payload: dict[str, Any] = {
        "name": interface["name"],
        "device": device_id,
        "type": interface_type,
        "status": interface_status_id,
    }

    optional_fields = [
        "enabled",
        "mgmt_only",
        "description",
        "mac_address",
        "mtu",
        "mode",
    ]
    for field in optional_fields:
        if field in interface and interface[field] is not None:
            # "none" is the UI sentinel for "no mode"; Nautobot rejects it
            if field == "mode" and interface[field] == "none":
                continue
            interface_payload[field] = interface[field]

    # Nautobot REST API requires VLAN references as {"id": uuid}. untagged_vlan_id
    # is already resolved by the caller (either passed through as-is if the
    # interface dict already carried a UUID, or resolved/created from a raw vid).
    if untagged_vlan_id:
        interface_payload["untagged_vlan"] = {"id": untagged_vlan_id}

    if tagged_vlan_ids:
        interface_payload["tagged_vlans"] = [{"id": vlan_id} for vlan_id in tagged_vlan_ids]

    return interface_payload


async def resolve_untagged_vlan_id(
    *,
    common: DeviceCommonService,
    interface: dict[str, Any],
    device_location_id: str | None,
    warnings: list[str],
) -> str | None:
    """Resolve ``interface["untagged_vlan"]`` to a Nautobot VLAN UUID.

    Accepts either an already-resolved UUID (existing manual-config behavior,
    passed straight through) or a raw VLAN vid (int), which is looked up —
    and created if missing — via ``DeviceCommonService.ensure_vlan_exists``.
    """
    raw_vlan = interface.get("untagged_vlan")
    if not raw_vlan or raw_vlan == "none":
        return None

    if is_valid_uuid(str(raw_vlan)):
        return str(raw_vlan)

    try:
        vid = int(raw_vlan)
    except TypeError, ValueError:
        warnings.append(
            f"Interface {interface['name']}: untagged_vlan {raw_vlan!r} is not a "
            "valid VLAN ID or UUID — omitting"
        )
        return None

    return await common.ensure_vlan_exists(vid, location_id=device_location_id)


async def resolve_tagged_vlan_ids(
    *,
    common: DeviceCommonService,
    interface: dict[str, Any],
    device_location_id: str | None,
    warnings: list[str],
) -> list[str]:
    """Resolve ``interface["tagged_vlans"]`` to a list of Nautobot VLAN UUIDs.

    Same accepted shapes as ``resolve_untagged_vlan_id`` (already-resolved UUID or
    raw VLAN vid), applied per entry.
    """
    raw_vlans = interface.get("tagged_vlans")
    if not isinstance(raw_vlans, list):
        return []

    vlan_ids: list[str] = []
    for raw_vlan in raw_vlans:
        if not raw_vlan or raw_vlan == "none":
            continue

        if is_valid_uuid(str(raw_vlan)):
            vlan_ids.append(str(raw_vlan))
            continue

        try:
            vid = int(raw_vlan)
        except TypeError, ValueError:
            warnings.append(
                f"Interface {interface['name']}: tagged_vlans entry {raw_vlan!r} is not "
                "a valid VLAN ID or UUID — omitting"
            )
            continue

        vlan_ids.append(await common.ensure_vlan_exists(vid, location_id=device_location_id))

    return vlan_ids
