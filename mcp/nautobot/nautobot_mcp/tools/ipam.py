"""IPAM tools: IP addresses, prefixes and namespaces."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from nautobot_mcp import networks
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
from nautobot_mcp.tools.dcim import device_name
from nautobot_mcp.vocabularies import NAMESPACES_SPEC, roles_spec, statuses_spec, tags_spec

IP_SELECTION = (
    "id address dns_name type description status { name } role { name } "
    "parent { prefix namespace { name } } tenant { name } tags { name } "
    "interfaces { name device { name } } primary_ip4_for { name }"
)
PREFIX_SELECTION = (
    "id prefix type status { name } role { name } namespace { name } description "
    "tenant { name } vlan { vid name } locations { name } tags { name } parent { prefix }"
)


def ip_item(row: dict[str, Any]) -> dict[str, Any]:
    parent = row.get("parent") or {}
    return {
        "id": row["id"],
        "address": row["address"],
        "prefix": parent.get("prefix"),
        "namespace": (parent.get("namespace") or {}).get("name"),
        "status": (row.get("status") or {}).get("name"),
        "role": (row.get("role") or {}).get("name"),
        "type": row.get("type"),
        "dns_name": row.get("dns_name") or "",
        "description": row.get("description") or "",
        "tenant": (row.get("tenant") or {}).get("name"),
        "tags": names(row.get("tags")),
        "assigned_to": [
            {"device": (i.get("device") or {}).get("name"), "interface": i["name"]}
            for i in row.get("interfaces") or []
        ],
        "primary_ip_for": names(row.get("primary_ip4_for")),
    }


def prefix_item(row: dict[str, Any]) -> dict[str, Any]:
    vlan = row.get("vlan")
    return {
        "id": row["id"],
        "prefix": row["prefix"],
        "type": row.get("type"),
        "namespace": (row.get("namespace") or {}).get("name"),
        "status": (row.get("status") or {}).get("name"),
        "role": (row.get("role") or {}).get("name"),
        "description": row.get("description") or "",
        "tenant": (row.get("tenant") or {}).get("name"),
        "vlan": f"{vlan['vid']} {vlan['name']}" if vlan else None,
        "locations": names(row.get("locations")),
        "parent": (row.get("parent") or {}).get("prefix"),
        "tags": names(row.get("tags")),
    }


def register(server: MCPServer, app: AppContext) -> None:
    """Add the IPAM tools to ``server``."""
    vocabularies = app.vocabularies

    async def named_filters(
        content_type: str, namespace: str | None, role: str | None, status: str | None,
        tag: str | None,
    ) -> tuple[dict[str, list[str]], dict[str, Any]]:
        """Resolve the vocabulary filters shared by IP addresses and prefixes."""
        filters: dict[str, list[str]] = {}
        applied: dict[str, Any] = {}
        specs = (
            ("namespace", "namespace", namespace, NAMESPACES_SPEC),
            ("role", "role", role, roles_spec(content_type)),
            ("status", "status", status, statuses_spec(content_type)),
            ("tag", "tags", tag, tags_spec(content_type)),
        )
        for param, filter_name, value, spec in specs:
            if value:
                canonical = (await vocabularies.get(spec)).resolve(value)
                filters[filter_name], applied[param] = [canonical], canonical
        return filters, applied

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
        filters, applied = await named_filters("ipam.ipaddress", namespace, role, status, tag)
        if address:
            filters["address"], applied["address"] = [networks.address(address)], address
        if prefix:
            normalized = networks.prefix(prefix)
            filters["prefix"], applied["prefix"] = [normalized], normalized
        if device:
            exact = await device_name(app, device.strip())
            filters["device"], applied["device"] = [exact], exact
        if dns_name_contains:
            filters["dns_name__ic"] = [dns_name_contains]
            applied["dns_name_contains"] = dns_name_contains
        page = await app.client.list_page(
            "ip_addresses", IP_SELECTION, filters, limit=limit, offset=offset
        )
        return envelope(
            [ip_item(row) for row in page.items], page, offset=offset, applied_filters=applied
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
        filters, applied = await named_filters("ipam.prefix", namespace, role, status, tag)
        if prefix:
            normalized = networks.prefix(prefix)
            filters["prefix"], applied["prefix"] = [normalized], normalized
        if within:
            normalized = networks.prefix(within)
            filters["within_include"], applied["within"] = [normalized], normalized
        if contains:
            checked = networks.address(contains)
            filters["contains"], applied["contains"] = [checked], checked
        if location:
            record = (await vocabularies.locations()).resolve(location)
            filters["location"], applied["location"] = [record.id], record.path
        page = await app.client.list_page(
            "prefixes", PREFIX_SELECTION, filters, limit=limit, offset=offset
        )
        return envelope(
            [prefix_item(row) for row in page.items], page, offset=offset, applied_filters=applied
        )

    @server.tool(annotations=READ_ONLY)
    @guarded
    async def list_namespaces() -> dict[str, Any]:
        """List IPAM namespaces (the same prefix can exist once per namespace)."""
        vocabulary = await vocabularies.get(NAMESPACES_SPEC)
        return envelope([{"name": n} for n in vocabulary.names], None, offset=0, applied_filters={})
