"""DCIM tools: devices, interfaces by MAC, device types and platforms (logic in nautobot_read)."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from nautobot_read.context import QueryContext
from nautobot_read.queries import dcim
from nautobot_read.queries import virtual_chassis as stacks
from nautobot_read.queries.common import DEFAULT_LIMIT
from pydantic import Field

from nautobot_mcp.tools.common import READ_ONLY, Limit, Offset, guarded


def register(server: MCPServer, app: QueryContext) -> None:
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
        return await dcim.list_devices(
            app, location=location, role=role, status=status, tag=tag, device_type=device_type,
            platform=platform, name_contains=name_contains, limit=limit, offset=offset,
        )

    @server.tool(annotations=READ_ONLY)
    @guarded
    async def get_device(
        device: Annotated[str, Field(description="Exact device name, or id.")],
    ) -> dict[str, Any]:
        """Get one device with its interfaces and their IP addresses.

        Device names are unique only within a location; if a name matches several devices the
        error lists them with their ids.
        """
        return await dcim.get_device(app, device=device)

    @server.tool(annotations=READ_ONLY)
    @guarded
    async def list_interfaces_by_mac(
        mac_address: Annotated[
            str,
            Field(description="A complete MAC address in any notation: aa:bb:cc:00:01:00, "
                  "aabb.cc00.0100 (Cisco), aa-bb-cc-00-01-00, in any case."),
        ],
        limit: Limit = DEFAULT_LIMIT,
        offset: Offset = 0,
    ) -> dict[str, Any]:
        """Find the interface, on any device, that has this MAC address in Nautobot.

        Give a complete MAC address in any notation (aa:bb:cc:00:01:00, aabb.cc00.0100,
        aa-bb-cc-00-01-00). Answers "on which interface can I find the MAC address
        aa:bb:cc:00:01:00?". Each row has
        device, device_id, interface, mac_address, type, enabled, status and ip_addresses.
        Several rows are possible (virtual and all-zero MAC addresses are shared), so report
        every row; an empty answer means no interface has that MAC address documented, not that
        it does not exist. This is the MAC address documented on an interface, NOT the MAC
        address table a switch has learned: for "behind which port does this host sit" read
        the switch itself (show mac address-table). Documented, not live.
        """
        return await dcim.list_interfaces_by_mac(
            app, mac_address=mac_address, limit=limit, offset=offset
        )

    @server.tool(annotations=READ_ONLY)
    @guarded
    async def list_device_types() -> dict[str, Any]:
        """List device type models with their manufacturer (valid values for device_type)."""
        return await dcim.list_device_types(app)

    @server.tool(annotations=READ_ONLY)
    @guarded
    async def list_platforms() -> dict[str, Any]:
        """List platforms (for example 'Cisco IOS') with manufacturer and network driver."""
        return await dcim.list_platforms(app)

    @server.tool(annotations=READ_ONLY)
    @guarded
    async def list_virtual_chassis(
        name_contains: Annotated[
            str | None, Field(description="Case-insensitive part of the virtual chassis name.")
        ] = None,
        limit: Limit = DEFAULT_LIMIT,
        offset: Offset = 0,
    ) -> dict[str, Any]:
        """List virtual chassis (Cisco stacks): master, member names in stack order, count."""
        return await stacks.list_virtual_chassis(
            app, name_contains=name_contains, limit=limit, offset=offset
        )

    @server.tool(annotations=READ_ONLY)
    @guarded
    async def get_virtual_chassis(
        virtual_chassis: Annotated[
            str, Field(description="Virtual chassis name (any case) or id.")
        ],
    ) -> dict[str, Any]:
        """Get one virtual chassis (stack) with every member device and which one is master."""
        return await stacks.get_virtual_chassis(app, virtual_chassis=virtual_chassis)
