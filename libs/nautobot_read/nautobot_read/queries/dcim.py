"""DCIM queries: devices, device types and platforms."""

from __future__ import annotations

from typing import Any

from nautobot_read.context import QueryContext
from nautobot_read.queries.common import DEFAULT_LIMIT, check_paging, envelope, names
from nautobot_read.queries.locations import directory_or_none, path_or_name, resolve_location
from nautobot_read.vocabularies import (
    DEVICE_TYPES_SPEC,
    PLATFORMS_SPEC,
    AmbiguousNameError,
    LocationDirectory,
    roles_spec,
    statuses_spec,
    tags_spec,
)
from nautobot_read.vocabulary import UUID_PATTERN, UnknownNameError

MAX_INTERFACES = 100
MAX_NAME_MATCHES = 6

DEVICE_SELECTION = (
    "id name serial role { name } status { name } "
    "device_type { model manufacturer { name } } platform { name } "
    "location { id name } primary_ip4 { address } tags { name }"
)
DEVICE_DETAIL_QUERY = (
    "query($id: ID!) { device(id: $id) { "
    "id name serial asset_tag comments role { name } status { name } "
    "device_type { model manufacturer { name } } platform { name } "
    "location { id name } rack { name } tenant { name } "
    "primary_ip4 { address } primary_ip6 { address } tags { name } } }"
)
# Interfaces are a bounded top-level page, not a nested selection: a nested list is built and
# parsed whole before it can be truncated.
INTERFACE_SELECTION = (
    "name type enabled mac_address description status { name } ip_addresses { address }"
)
DEVICE_NAME_QUERY = "query($id: ID!) { device(id: $id) { name } }"
DEVICE_TYPE_SELECTION = "model manufacturer { name }"
PLATFORM_SELECTION = "name manufacturer { name } network_driver"


def device_item(row: dict[str, Any], directory: LocationDirectory | None) -> dict[str, Any]:
    """One device row as shown to the model."""
    device_type = row.get("device_type") or {}
    location = row.get("location") or {}
    return {
        "id": row["id"],
        "name": row["name"],
        "role": (row.get("role") or {}).get("name"),
        "status": (row.get("status") or {}).get("name"),
        "device_type": device_type.get("model"),
        "manufacturer": (device_type.get("manufacturer") or {}).get("name"),
        "platform": (row.get("platform") or {}).get("name"),
        "location": path_or_name(directory, location.get("id", ""), location.get("name")),
        "primary_ip4": (row.get("primary_ip4") or {}).get("address"),
        "serial": row.get("serial") or "",
        "tags": names(row.get("tags")),
    }


def _interface_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": row["name"],
        "type": row.get("type"),
        "enabled": row.get("enabled"),
        "mac_address": row.get("mac_address"),
        "description": row.get("description") or "",
        "status": (row.get("status") or {}).get("name"),
        "ip_addresses": [ip["address"] for ip in row.get("ip_addresses") or []],
    }


async def list_devices(
    ctx: QueryContext,
    *,
    location: str | None = None,
    role: str | None = None,
    status: str | None = None,
    tag: str | None = None,
    device_type: str | None = None,
    platform: str | None = None,
    name_contains: str | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    """Devices, filtered. Filters combine with AND; a location includes its child locations."""
    check_paging(limit, offset)
    vocabularies = ctx.vocabularies
    filters: dict[str, list[str]] = {}
    applied: dict[str, Any] = {}
    directory = await directory_or_none(ctx)
    if location:
        location_id, location_label = await resolve_location(ctx, location, directory)
        filters["location"], applied["location"] = [location_id], location_label
    named = (
        ("role", "role", role, roles_spec("dcim.device")),
        ("status", "status", status, statuses_spec("dcim.device")),
        ("tag", "tags", tag, tags_spec("dcim.device")),
        ("device_type", "device_type", device_type, DEVICE_TYPES_SPEC),
        ("platform", "platform", platform, PLATFORMS_SPEC),
    )
    for param, filter_name, value, spec in named:
        if value:
            canonical = (await vocabularies.get(spec)).resolve(value)
            filters[filter_name], applied[param] = [canonical], canonical
    if name_contains:
        filters["name__ic"], applied["name_contains"] = [name_contains], name_contains
    page = await ctx.client.list_page(
        "devices", DEVICE_SELECTION, filters, limit=limit, offset=offset
    )
    items = [device_item(row, directory) for row in page.items]
    return envelope(items, page, offset=offset, applied_filters=applied)


async def get_device(ctx: QueryContext, *, device: str) -> dict[str, Any]:
    """One device with its interfaces and their IP addresses.

    Device names are unique only within a location; if a name matches several devices the
    error lists them with their ids.
    """
    device_id = await _device_id(ctx, device.strip())
    data = await ctx.client.graphql(DEVICE_DETAIL_QUERY, {"id": device_id})
    row = data.get("device")
    if not row:
        raise UnknownNameError(f"No device with id '{device_id}'.")
    directory = await directory_or_none(ctx)
    item = device_item(row, directory)
    page = await ctx.client.list_page(
        "interfaces", INTERFACE_SELECTION, {"device_id": [device_id]},
        limit=MAX_INTERFACES, offset=0,
    )
    item.update(
        asset_tag=row.get("asset_tag"),
        comments=row.get("comments") or "",
        rack=(row.get("rack") or {}).get("name"),
        tenant=(row.get("tenant") or {}).get("name"),
        primary_ip6=(row.get("primary_ip6") or {}).get("address"),
        interfaces=[_interface_item(i) for i in page.items],
        interfaces_truncated=page.has_more,
    )
    return item


async def list_interfaces(
    ctx: QueryContext,
    *,
    device: str,
    name_contains: str | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    """The interfaces of one device, paged.

    ``get_device`` shows at most ``MAX_INTERFACES`` of them; this is the way to the rest of a
    device with hundreds, optionally narrowed by part of the name.
    """
    check_paging(limit, offset)
    device_id, resolved_name = await _device_ref(ctx, device.strip())
    filters = {"device_id": [device_id]}
    # The device actually queried: a short or differently cased name may have matched another
    # spelling, and interface rows carry no device of their own.
    applied: dict[str, Any] = {"device": resolved_name}
    if name_contains:
        filters["name__ic"], applied["name_contains"] = [name_contains], name_contains
    page = await ctx.client.list_page(
        "interfaces", INTERFACE_SELECTION, filters, limit=limit, offset=offset
    )
    items = [_interface_item(row) for row in page.items]
    return envelope(items, page, offset=offset, applied_filters=applied)


async def list_device_types(ctx: QueryContext) -> dict[str, Any]:
    """Device type models with their manufacturer (valid values for device_type)."""
    rows = await ctx.client.list_all("device_types", DEVICE_TYPE_SELECTION)
    items = [
        {"model": r["model"], "manufacturer": (r.get("manufacturer") or {}).get("name")}
        for r in rows
    ]
    return envelope(items, None, offset=0, applied_filters={})


async def list_platforms(ctx: QueryContext) -> dict[str, Any]:
    """Platforms (for example 'Cisco IOS') with manufacturer and network driver."""
    rows = await ctx.client.list_all("platforms", PLATFORM_SELECTION)
    items = [
        {
            "name": r["name"],
            "manufacturer": (r.get("manufacturer") or {}).get("name"),
            "network_driver": r.get("network_driver") or "",
        }
        for r in rows
    ]
    return envelope(items, None, offset=0, applied_filters={})


async def _device_id(ctx: QueryContext, device: str) -> str:
    """Resolve a device name to its id; ids pass through."""
    if UUID_PATTERN.match(device):
        return device.lower()
    return (await _device_by_name(ctx, device))["id"]


async def _device_ref(ctx: QueryContext, device: str) -> tuple[str, str]:
    """The id and the exact name of a device given by name or id."""
    if UUID_PATTERN.match(device):
        return device.lower(), await device_name(ctx, device)
    row = await _device_by_name(ctx, device)
    return row["id"], row["name"]


async def device_name(ctx: QueryContext, device: str) -> str:
    """The exact name of a device given by name or id.

    Some Nautobot filters (for example ``ip_addresses(device:)``) work by exact name only and
    silently return nothing for anything else.
    """
    if UUID_PATTERN.match(device):
        data = await ctx.client.graphql(DEVICE_NAME_QUERY, {"id": device.lower()})
        found = data.get("device")
        if not found:
            raise UnknownNameError(f"No device with id '{device}'.")
        return found["name"]
    return (await _device_by_name(ctx, device))["name"]


# How a device name is looked up, in order, until one finds something: exactly, ignoring case,
# then as the start of a full name (``lab`` finds ``LAB.local.zz``). A name that is exact for one
# device never also matches another, and a short name in two domains stays ambiguous.
_NAME_LOOKUPS = (("name", ""), ("name__ie", ""), ("name__isw", "."))


async def _device_by_name(ctx: QueryContext, device: str) -> dict[str, Any]:
    for filter_name, suffix in _NAME_LOOKUPS:
        page = await ctx.client.list_page(
            "devices", "id name location { id name }", {filter_name: [device + suffix]},
            limit=MAX_NAME_MATCHES, offset=0,
        )
        if len(page.items) == 1:
            return page.items[0]
        if page.items:
            total = f"at least {len(page.items)}" if page.has_more else str(len(page.items))
            listing = "; ".join(
                f"{r['name']} ({(r.get('location') or {}).get('name')}, id {r['id']})"
                for r in page.items
            )
            raise AmbiguousNameError(
                f"'{device}' matches {total} devices: {listing}"
                f"{' (list truncated)' if page.has_more else ''}. Retry with the id."
            )
    raise UnknownNameError(
        f"No device '{device}' (tried the exact name, the name ignoring case, and as the "
        f"start of a full name such as '{device}.example.com'). Use list_devices with "
        "name_contains to search."
    )
