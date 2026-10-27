"""Organization tools: locations, location types, roles, statuses and tags."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from nautobot_mcp.context import AppContext
from nautobot_mcp.tools.common import (
    DEFAULT_LIMIT,
    READ_ONLY,
    ContentType,
    Limit,
    Offset,
    envelope,
    guarded,
    names,
)
from nautobot_mcp.vocabularies import (
    LOCATION_TYPES_SPEC,
    LocationDirectory,
    roles_spec,
    statuses_spec,
    tags_spec,
)
from nautobot_mcp.vocabulary import UnknownNameError

LOCATION_SELECTION = (
    "id name description location_type { name } parent { id name } status { name } tags { name }"
)
LOCATION_DETAIL_QUERY = (
    "query($id: ID!) { location(id: $id) { "
    "id name description facility physical_address time_zone latitude longitude "
    "location_type { name } parent { id name } status { name } tags { name } "
    "children { name location_type { name } } } }"
)
LOCATION_TYPE_SELECTION = "name nestable parent { name } content_types { app_label model }"


def location_item(row: dict[str, Any], directory: LocationDirectory) -> dict[str, Any]:
    """One location row as shown to the model, with its full path for disambiguation."""
    return {
        "id": row["id"],
        "name": row["name"],
        "path": directory.path_of(row["id"]) or row["name"],
        "location_type": (row.get("location_type") or {}).get("name"),
        "status": (row.get("status") or {}).get("name"),
        "parent": (row.get("parent") or {}).get("name"),
        "description": row.get("description") or "",
        "tags": names(row.get("tags")),
    }


def register(server: MCPServer, app: AppContext) -> None:
    """Add the organization tools to ``server``."""

    @server.tool(annotations=READ_ONLY)
    @guarded
    async def list_locations(
        location_type: Annotated[
            str | None,
            Field(description="Location type name, e.g. 'Country'. See list_location_types."),
        ] = None,
        parent: Annotated[
            str | None,
            Field(
                description="Only direct children of this location "
                "(name, 'Parent → Name' path, or id)."
            ),
        ] = None,
        status: Annotated[str | None, Field(description="Status name, e.g. 'Active'.")] = None,
        tag: Annotated[str | None, Field(description="Tag name.")] = None,
        name_contains: Annotated[
            str | None, Field(description="Case-insensitive part of the location name.")
        ] = None,
        limit: Limit = DEFAULT_LIMIT,
        offset: Offset = 0,
    ) -> dict[str, Any]:
        """List locations (countries, regions, cities, sites, ...) of the Nautobot instance.

        Locations form a tree; each item has a `path` such as 'Germany → Berlin'. Filters
        combine with AND. Names are matched case-insensitively; an unknown name returns the
        closest and the available names.
        """
        filters: dict[str, list[str]] = {}
        applied: dict[str, Any] = {}
        vocabularies = app.vocabularies
        if location_type:
            canonical = (await vocabularies.get(LOCATION_TYPES_SPEC)).resolve(location_type)
            filters["location_type"], applied["location_type"] = [canonical], canonical
        directory = await vocabularies.locations()
        if parent:
            record = directory.resolve(parent)
            filters["parent"], applied["parent"] = [record.id], record.path
        if status:
            canonical = (await vocabularies.get(statuses_spec("dcim.location"))).resolve(status)
            filters["status"], applied["status"] = [canonical], canonical
        if tag:
            canonical = (await vocabularies.get(tags_spec("dcim.location"))).resolve(tag)
            filters["tags"], applied["tag"] = [canonical], canonical
        if name_contains:
            filters["name__ic"], applied["name_contains"] = [name_contains], name_contains
        page = await app.client.list_page(
            "locations", LOCATION_SELECTION, filters, limit=limit, offset=offset
        )
        items = [location_item(row, directory) for row in page.items]
        return envelope(items, page, offset=offset, applied_filters=applied)

    @server.tool(annotations=READ_ONLY)
    @guarded
    async def get_location(
        location: Annotated[
            str, Field(description="Location name, 'Parent → Name' path, or id.")
        ],
    ) -> dict[str, Any]:
        """Get one location with its address data, parent and direct children."""
        directory = await app.vocabularies.locations()
        record = directory.resolve(location)
        data = await app.client.graphql(LOCATION_DETAIL_QUERY, {"id": record.id})
        row = data.get("location")
        if not row:
            raise UnknownNameError(f"No location with id '{record.id}'.")
        item = location_item(row, directory)
        item["children"] = [
            {"name": c["name"], "location_type": (c.get("location_type") or {}).get("name")}
            for c in row.get("children") or []
        ]
        for key in ("facility", "physical_address", "time_zone", "latitude", "longitude"):
            item[key] = row.get(key)
        return item

    @server.tool(annotations=READ_ONLY)
    @guarded
    async def list_location_types() -> dict[str, Any]:
        """List location types and their hierarchy (for example Country > State > City)."""
        rows = await app.client.list_all("location_types", LOCATION_TYPE_SELECTION)
        items = [
            {
                "name": row["name"],
                "parent": (row.get("parent") or {}).get("name"),
                "nestable": row.get("nestable"),
            }
            for row in rows
        ]
        return envelope(items, None, offset=0, applied_filters={})

    @server.tool(annotations=READ_ONLY)
    @guarded
    async def list_roles(
        content_type: Annotated[
            ContentType, Field(description="Object type the roles apply to, e.g. 'dcim.device'.")
        ] = "dcim.device",
    ) -> dict[str, Any]:
        """List the role names for devices, IP addresses or prefixes (they differ per type)."""
        vocabulary = await app.vocabularies.get(roles_spec(content_type))
        return _name_list(vocabulary.names, content_type)

    @server.tool(annotations=READ_ONLY)
    @guarded
    async def list_statuses(
        content_type: Annotated[
            ContentType, Field(description="Object type the statuses apply to, e.g. 'dcim.device'.")
        ] = "dcim.device",
    ) -> dict[str, Any]:
        """List the status names valid for devices, locations, IP addresses or prefixes."""
        vocabulary = await app.vocabularies.get(statuses_spec(content_type))
        return _name_list(vocabulary.names, content_type)

    @server.tool(annotations=READ_ONLY)
    @guarded
    async def list_tags(
        content_type: Annotated[
            ContentType, Field(description="Object type the tags can be applied to.")
        ] = "dcim.device",
    ) -> dict[str, Any]:
        """List the tag names that can be applied to devices, locations, IPs or prefixes."""
        vocabulary = await app.vocabularies.get(tags_spec(content_type))
        return _name_list(vocabulary.names, content_type)


def _name_list(values: tuple[str, ...], content_type: str) -> dict[str, Any]:
    return envelope(
        [{"name": value} for value in values],
        None,
        offset=0,
        applied_filters={"content_type": content_type},
    )
