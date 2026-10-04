"""Resolve a Nautobot object's human-readable name to its UUID.

Wraps the per-domain resolver methods already exposed on ``DeviceCommonService`` behind
one dispatch table, keyed by the small set of object kinds a Nautobot job's
``ObjectVar``/``MultiObjectVar`` parameters (or an operator-picked equivalent) can
reference. Used by ``start_nautobot_job``'s executor (runtime, per device) and by the
``/sources/nautobot/resolve-object`` router (design-time "test resolve").
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.nautobot.devices.common import DeviceCommonService

UUID_RESOURCE_TYPES = frozenset(
    {"location", "role", "status", "platform", "device", "device_type", "namespace", "rack"}
)

# Maps a Nautobot job ObjectVar/MultiObjectVar's declared `model` (Django
# app_label.model_name) to the resource-type keys above. Mirrored on the frontend in
# start-nautobot-job/uuid-resolution.ts.
OBJECTVAR_MODEL_TO_RESOURCE_TYPE: dict[str, str] = {
    "dcim.location": "location",
    "dcim.device": "device",
    "dcim.platform": "platform",
    "dcim.rack": "rack",
    "dcim.devicetype": "device_type",
    "extras.role": "role",
    "extras.status": "status",
    "ipam.namespace": "namespace",
}


async def resolve_nautobot_uuid(
    common: DeviceCommonService,
    resource_type: str,
    value: str,
    *,
    content_type: str | None = None,
) -> str:
    """Resolve ``value`` (a name) to a Nautobot UUID for the given ``resource_type``.

    Raises ``ValueError`` for an unknown ``resource_type`` or when the object can't be
    found — the same exception type the executor's per-device failure handling already
    catches for other resolution errors.
    """
    name = value.strip()
    if not name:
        raise ValueError(f"cannot resolve an empty {resource_type} value to a UUID")

    if resource_type == "location":
        resolved = await common.resolve_location_id(name)
    elif resource_type == "role":
        resolved = await common.resolve_role_id_for_content_type(
            name, content_type or "dcim.device"
        )
    elif resource_type == "status":
        resolved = await common.resolve_status_id(name, content_type or "dcim.device")
    elif resource_type == "platform":
        resolved = await common.resolve_platform_id(name)
    elif resource_type == "device":
        resolved = await common.resolve_device_id(device_name=name)
    elif resource_type == "device_type":
        resolved = await common.resolve_device_type_id(name)
    elif resource_type == "namespace":
        resolved = await common.resolve_namespace_id(name)
    elif resource_type == "rack":
        resolved = await common.resolve_rack_id(name)
    else:
        raise ValueError(f"unsupported UUID resource_type: {resource_type!r}")

    if not resolved:
        raise ValueError(f"could not resolve {resource_type} {name!r} to a UUID")
    return resolved
