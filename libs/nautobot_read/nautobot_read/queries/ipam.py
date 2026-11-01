"""IPAM queries: IP addresses, prefixes and namespaces."""

from __future__ import annotations

from typing import Any

from nautobot_read import networks
from nautobot_read.context import QueryContext
from nautobot_read.queries.common import DEFAULT_LIMIT, check_paging, envelope, names
from nautobot_read.queries.dcim import device_name
from nautobot_read.queries.locations import directory_or_none, resolve_location
from nautobot_read.vocabularies import NAMESPACES_SPEC, roles_spec, statuses_spec, tags_spec

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


async def _named_filters(
    ctx: QueryContext,
    content_type: str,
    namespace: str | None,
    role: str | None,
    status: str | None,
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
            canonical = (await ctx.vocabularies.get(spec)).resolve(value)
            filters[filter_name], applied[param] = [canonical], canonical
    return filters, applied


async def list_ip_addresses(
    ctx: QueryContext,
    *,
    address: str | None = None,
    prefix: str | None = None,
    device: str | None = None,
    namespace: str | None = None,
    role: str | None = None,
    status: str | None = None,
    tag: str | None = None,
    dns_name_contains: str | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    """IP addresses, filtered. Filters combine with AND."""
    check_paging(limit, offset)
    filters, applied = await _named_filters(ctx, "ipam.ipaddress", namespace, role, status, tag)
    if address:
        filters["address"], applied["address"] = [networks.address(address)], address
    if prefix:
        normalized = networks.prefix(prefix)
        filters["prefix"], applied["prefix"] = [normalized], normalized
    if device:
        exact = await device_name(ctx, device.strip())
        filters["device"], applied["device"] = [exact], exact
    if dns_name_contains:
        filters["dns_name__ic"] = [dns_name_contains]
        applied["dns_name_contains"] = dns_name_contains
    page = await ctx.client.list_page(
        "ip_addresses", IP_SELECTION, filters, limit=limit, offset=offset
    )
    return envelope(
        [ip_item(row) for row in page.items], page, offset=offset, applied_filters=applied
    )


async def list_prefixes(
    ctx: QueryContext,
    *,
    prefix: str | None = None,
    within: str | None = None,
    contains: str | None = None,
    location: str | None = None,
    namespace: str | None = None,
    role: str | None = None,
    status: str | None = None,
    tag: str | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    """IP prefixes (networks), filtered. Filters combine with AND."""
    check_paging(limit, offset)
    filters, applied = await _named_filters(ctx, "ipam.prefix", namespace, role, status, tag)
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
        location_id, location_label = await resolve_location(
            ctx, location, await directory_or_none(ctx)
        )
        filters["location"], applied["location"] = [location_id], location_label
    page = await ctx.client.list_page(
        "prefixes", PREFIX_SELECTION, filters, limit=limit, offset=offset
    )
    return envelope(
        [prefix_item(row) for row in page.items], page, offset=offset, applied_filters=applied
    )


async def list_namespaces(ctx: QueryContext) -> dict[str, Any]:
    """IPAM namespaces (the same prefix can exist once per namespace)."""
    vocabulary = await ctx.vocabularies.get(NAMESPACES_SPEC)
    return envelope([{"name": n} for n in vocabulary.names], None, offset=0, applied_filters={})
