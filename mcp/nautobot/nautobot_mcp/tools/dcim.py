"""DCIM tools: devices, device types and platforms."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from nautobot_mcp.context import AppContext
from nautobot_mcp.tools.common import (
    DEFAULT_LIMIT,
    READ_ONLY,
    Limit,
    Offset,
    envelope,
    guarded,
    names,
)
from nautobot_mcp.vocabularies import (
    DEVICE_TYPES_SPEC,
    PLATFORMS_SPEC,
    AmbiguousNameError,
    LocationDirectory,
    roles_spec,
    statuses_spec,
    tags_spec,
)
from nautobot_mcp.vocabulary import UUID_PATTERN, UnknownNameError

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


def device_item(row: dict[str, Any], directory: LocationDirectory) -> dict[str, Any]:
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
        "location": directory.path_of(location.get("id", "")) or location.get("name"),
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


def register(server: MCPServer, app: AppContext) -> None:
    """Add the DCIM tools to ``server``."""

    @server.tool(annotations=READ_ONLY)
    @guarded
    async def list_devices(
        location: Annotated[
            str | None,
            Field(description="Location name, 'Parent → Name' path, or id. Includes devices in "
                  "child locations (a country returns the devices of its cities)."),
        ] = None,
        role: Annotated[
            str | None, Field(description="Device role name, e.g. 'Network'. See list_roles.")
        ] = None,
        status: Annotated[str | None, Field(description="Device status, e.g. 'Active'.")] = None,
        tag: Annotated[str | None, Field(description="Tag name.")] = None,
        device_type: Annotated[
            str | None, Field(description="Device type model name. See list_device_types.")
        ] = None,
        platform: Annotated[
            str | None, Field(description="Platform name, e.g. 'Cisco IOS'. See list_platforms.")
        ] = None,
        name_contains: Annotated[
            str | None, Field(description="Case-insensitive part of the device name.")
        ] = None,
        limit: Limit = DEFAULT_LIMIT,
        offset: Offset = 0,
    ) -> dict[str, Any]:
        """List devices, optionally filtered. Filters combine with AND.

        Filtering by a location includes devices in its child locations. Names are matched
        case-insensitively; an unknown name returns the closest and the available names.
        Words like "router" or "switch" may be a role, a device type or a platform in this
        instance: check list_roles, list_device_types and list_platforms.
        """
        vocabularies = app.vocabularies
        filters: dict[str, list[str]] = {}
        applied: dict[str, Any] = {}
        directory = await vocabularies.locations()
        if location:
            record = directory.resolve(location)
            filters["location"], applied["location"] = [record.id], record.path
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
        page = await app.client.list_page(
            "devices", DEVICE_SELECTION, filters, limit=limit, offset=offset
        )
        items = [device_item(row, directory) for row in page.items]
        return envelope(items, page, offset=offset, applied_filters=applied)

    @server.tool(annotations=READ_ONLY)
    @guarded
    async def get_device(
        device: Annotated[str, Field(description="Exact device name, or id.")],
    ) -> dict[str, Any]:
        """Get one device with its interfaces and their IP addresses.

        Device names are unique only within a location; if a name matches several devices the
        error lists them with their ids.
        """
        device_id = await _device_id(app, device.strip())
        data = await app.client.graphql(DEVICE_DETAIL_QUERY, {"id": device_id})
        row = data.get("device")
        if not row:
            raise UnknownNameError(f"No device with id '{device_id}'.")
        directory = await app.vocabularies.locations()
        item = device_item(row, directory)
        page = await app.client.list_page(
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

    @server.tool(annotations=READ_ONLY)
    @guarded
    async def list_device_types() -> dict[str, Any]:
        """List device type models with their manufacturer (valid values for device_type)."""
        rows = await app.client.list_all("device_types", DEVICE_TYPE_SELECTION)
        items = [
            {"model": r["model"], "manufacturer": (r.get("manufacturer") or {}).get("name")}
            for r in rows
        ]
        return envelope(items, None, offset=0, applied_filters={})

    @server.tool(annotations=READ_ONLY)
    @guarded
    async def list_platforms() -> dict[str, Any]:
        """List platforms (for example 'Cisco IOS') with manufacturer and network driver."""
        rows = await app.client.list_all("platforms", PLATFORM_SELECTION)
        items = [
            {
                "name": r["name"],
                "manufacturer": (r.get("manufacturer") or {}).get("name"),
                "network_driver": r.get("network_driver") or "",
            }
            for r in rows
        ]
        return envelope(items, None, offset=0, applied_filters={})


async def _device_id(app: AppContext, device: str) -> str:
    """Resolve a device name to its id; ids pass through."""
    if UUID_PATTERN.match(device):
        return device.lower()
    return (await _device_by_name(app, device))["id"]


async def device_name(app: AppContext, device: str) -> str:
    """The exact name of a device given by name or id.

    Some Nautobot filters (for example ``ip_addresses(device:)``) work by exact name only and
    silently return nothing for anything else.
    """
    if UUID_PATTERN.match(device):
        data = await app.client.graphql(DEVICE_NAME_QUERY, {"id": device.lower()})
        found = data.get("device")
        if not found:
            raise UnknownNameError(f"No device with id '{device}'.")
        return found["name"]
    return (await _device_by_name(app, device))["name"]


async def _device_by_name(app: AppContext, device: str) -> dict[str, Any]:
    page = await app.client.list_page(
        "devices", "id name location { id name }", {"name": [device]},
        limit=MAX_NAME_MATCHES, offset=0,
    )
    if not page.items:
        raise UnknownNameError(
            f"No device '{device}'. Names must match exactly; use list_devices with "
            "name_contains to search."
        )
    if len(page.items) > 1:
        total = f"at least {len(page.items)}" if page.has_more else str(len(page.items))
        listing = "; ".join(
            f"{r['name']} ({(r.get('location') or {}).get('name')}, id {r['id']})"
            for r in page.items
        )
        raise AmbiguousNameError(
            f"'{device}' matches {total} devices: {listing}"
            f"{' (list truncated)' if page.has_more else ''}. Retry with the id."
        )
    return page.items[0]
