"""IPAM tools: IP addresses, prefixes and namespaces (the logic is in nautobot_read)."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from nautobot_read.context import QueryContext
from nautobot_read.queries import ipam
from nautobot_read.queries.common import DEFAULT_LIMIT
from pydantic import Field

from nautobot_mcp.tools.common import READ_ONLY, Limit, Offset, guarded


def register(server: MCPServer, app: QueryContext) -> None:
    """Add the IPAM tools to ``server``."""

    @server.tool(annotations=READ_ONLY)
    @guarded
    async def list_ip_addresses(
        address: Annotated[
            str | None,
            Field(description="Exact IP address, with or without mask, e.g. '10.0.0.2/24'."),
        ] = None,
        prefix: Annotated[
            str | None,
            Field(description="Only addresses inside this network, e.g. '10.0.0.0/24'."),
        ] = None,
        device: Annotated[
            str | None, Field(description="Only addresses assigned to this device (name or id).")
        ] = None,
        namespace: Annotated[
            str | None, Field(description="Namespace name. See list_namespaces.")
        ] = None,
        role: Annotated[str | None, Field(description="IP role, e.g. 'Loopback' or 'VIP'.")] = None,
        status: Annotated[str | None, Field(description="IP status, e.g. 'Active'.")] = None,
        tag: Annotated[str | None, Field(description="Tag name.")] = None,
        dns_name_contains: Annotated[
            str | None, Field(description="Case-insensitive part of the DNS name.")
        ] = None,
        limit: Limit = DEFAULT_LIMIT,
        offset: Offset = 0,
    ) -> dict[str, Any]:
        """List IP addresses, optionally filtered. Filters combine with AND.

        Each item shows its prefix, namespace and the device interfaces it is assigned to.
        Addresses and prefixes are validated first; names are matched case-insensitively.
        """
        return await ipam.list_ip_addresses(
            app, address=address, prefix=prefix, device=device, namespace=namespace, role=role,
            status=status, tag=tag, dns_name_contains=dns_name_contains, limit=limit,
            offset=offset,
        )

    @server.tool(annotations=READ_ONLY)
    @guarded
    async def list_prefixes(
        prefix: Annotated[
            str | None, Field(description="Exact prefix in CIDR notation, e.g. '10.0.0.0/24'.")
        ] = None,
        within: Annotated[
            str | None,
            Field(description="Prefixes inside this network, including itself, e.g. '10.0.0.0/8'."),
        ] = None,
        contains: Annotated[
            str | None,
            Field(description="Prefixes that contain this address or network, e.g. '10.0.0.2'."),
        ] = None,
        location: Annotated[
            str | None,
            Field(description="Prefixes assigned to this location (name, path, or id). "
                  "Child locations are not verified to be included."),
        ] = None,
        namespace: Annotated[
            str | None, Field(description="Namespace name. See list_namespaces.")
        ] = None,
        role: Annotated[str | None, Field(description="Prefix role name.")] = None,
        status: Annotated[str | None, Field(description="Prefix status, e.g. 'Active'.")] = None,
        tag: Annotated[str | None, Field(description="Tag name.")] = None,
        limit: Limit = DEFAULT_LIMIT,
        offset: Offset = 0,
    ) -> dict[str, Any]:
        """List IP prefixes (networks), optionally filtered. Filters combine with AND."""
        return await ipam.list_prefixes(
            app, prefix=prefix, within=within, contains=contains, location=location,
            namespace=namespace, role=role, status=status, tag=tag, limit=limit, offset=offset,
        )

    @server.tool(annotations=READ_ONLY)
    @guarded
    async def list_namespaces() -> dict[str, Any]:
        """List IPAM namespaces (the same prefix can exist once per namespace)."""
        return await ipam.list_namespaces(app)
