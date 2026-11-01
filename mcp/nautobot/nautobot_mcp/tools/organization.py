"""Organization tools: locations, location types, roles, statuses and tags.

The logic is in ``nautobot_read.queries.organization``; this module adds the MCP schema.
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from nautobot_read.context import QueryContext
from nautobot_read.queries import organization
from nautobot_read.queries.common import DEFAULT_LIMIT
from pydantic import Field

from nautobot_mcp.tools.common import READ_ONLY, ContentType, Limit, Offset, guarded


def register(server: MCPServer, app: QueryContext) -> None:
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
        return await organization.list_locations(
            app, location_type=location_type, parent=parent, status=status, tag=tag,
            name_contains=name_contains, limit=limit, offset=offset,
        )

    @server.tool(annotations=READ_ONLY)
    @guarded
    async def get_location(
        location: Annotated[
            str, Field(description="Location name, 'Parent → Name' path, or id.")
        ],
    ) -> dict[str, Any]:
        """Get one location with its address data, parent and direct children."""
        return await organization.get_location(app, location=location)

    @server.tool(annotations=READ_ONLY)
    @guarded
    async def list_location_types() -> dict[str, Any]:
        """List location types and their hierarchy (for example Country > State > City)."""
        return await organization.list_location_types(app)

    @server.tool(annotations=READ_ONLY)
    @guarded
    async def list_roles(
        content_type: Annotated[
            ContentType, Field(description="Object type the roles apply to, e.g. 'dcim.device'.")
        ] = "dcim.device",
    ) -> dict[str, Any]:
        """List the role names for devices, IP addresses or prefixes (they differ per type)."""
        return await organization.list_roles(app, content_type=content_type)

    @server.tool(annotations=READ_ONLY)
    @guarded
    async def list_statuses(
        content_type: Annotated[
            ContentType, Field(description="Object type the statuses apply to, e.g. 'dcim.device'.")
        ] = "dcim.device",
    ) -> dict[str, Any]:
        """List the status names valid for devices, locations, IP addresses or prefixes."""
        return await organization.list_statuses(app, content_type=content_type)

    @server.tool(annotations=READ_ONLY)
    @guarded
    async def list_tags(
        content_type: Annotated[
            ContentType, Field(description="Object type the tags can be applied to.")
        ] = "dcim.device",
    ) -> dict[str, Any]:
        """List the tag names that can be applied to devices, locations, IPs or prefixes."""
        return await organization.list_tags(app, content_type=content_type)
