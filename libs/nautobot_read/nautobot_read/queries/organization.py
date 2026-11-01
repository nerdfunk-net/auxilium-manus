"""Organization queries: locations, location types, roles, statuses and tags."""

from __future__ import annotations

from typing import Any

from nautobot_read.context import QueryContext
from nautobot_read.queries.common import DEFAULT_LIMIT, check_paging, envelope, names
from nautobot_read.queries.locations import directory_or_none, path_or_name, resolve_location
from nautobot_read.vocabularies import (
    LOCATION_TYPES_SPEC,
    PATH_SEPARATOR,
    LocationDirectory,
    roles_spec,
    statuses_spec,
    tags_spec,
)
from nautobot_read.vocabulary import UnknownNameError

LOCATION_SELECTION = (
    "id name description location_type { name } parent { id name } status { name } tags { name }"
)
LOCATION_DETAIL_QUERY = (
    "query($id: ID!) { location(id: $id) { "
    "id name description facility physical_address time_zone latitude longitude "
    "location_type { name } parent { id name } status { name } tags { name } "
    "children { id name location_type { name } } } }"
)
LOCATION_TYPE_SELECTION = "name nestable parent { name } content_types { app_label model }"


def location_item(
    row: dict[str, Any], directory: LocationDirectory | None
) -> dict[str, Any]:
    """One location row as shown to the model, with its full path for disambiguation."""
    return {
        "id": row["id"],
        "name": row["name"],
        "path": path_or_name(directory, row["id"], row["name"]),
        "location_type": (row.get("location_type") or {}).get("name"),
        "status": (row.get("status") or {}).get("name"),
        "parent": (row.get("parent") or {}).get("name"),
        "description": row.get("description") or "",
        "tags": names(row.get("tags")),
    }


async def list_locations(
    ctx: QueryContext,
    *,
    location_type: str | None = None,
    parent: str | None = None,
    status: str | None = None,
    tag: str | None = None,
    name_contains: str | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    """Locations of the instance, filtered. Filters combine with AND."""
    check_paging(limit, offset)
    filters: dict[str, list[str]] = {}
    applied: dict[str, Any] = {}
    vocabularies = ctx.vocabularies
    if location_type:
        canonical = (await vocabularies.get(LOCATION_TYPES_SPEC)).resolve(location_type)
        filters["location_type"], applied["location_type"] = [canonical], canonical
    directory = await directory_or_none(ctx)
    if parent:
        parent_id, parent_label = await resolve_location(ctx, parent, directory)
        filters["parent"], applied["parent"] = [parent_id], parent_label
    if status:
        canonical = (await vocabularies.get(statuses_spec("dcim.location"))).resolve(status)
        filters["status"], applied["status"] = [canonical], canonical
    if tag:
        canonical = (await vocabularies.get(tags_spec("dcim.location"))).resolve(tag)
        filters["tags"], applied["tag"] = [canonical], canonical
    if name_contains:
        filters["name__ic"], applied["name_contains"] = [name_contains], name_contains
    page = await ctx.client.list_page(
        "locations", LOCATION_SELECTION, filters, limit=limit, offset=offset
    )
    items = [location_item(row, directory) for row in page.items]
    return envelope(items, page, offset=offset, applied_filters=applied)


def _child_item(
    child: dict[str, Any], parent_path: str, directory: LocationDirectory | None
) -> dict[str, Any]:
    plain = f"{parent_path}{PATH_SEPARATOR}{child['name']}"
    return {
        "id": child["id"],
        "name": child["name"],
        "location_type": (child.get("location_type") or {}).get("name"),
        "path": path_or_name(directory, child["id"], plain),
    }


async def get_location(ctx: QueryContext, *, location: str) -> dict[str, Any]:
    """One location with its address data, parent and direct children."""
    directory = await directory_or_none(ctx)
    location_id, _label = await resolve_location(ctx, location, directory)
    data = await ctx.client.graphql(LOCATION_DETAIL_QUERY, {"id": location_id})
    row = data.get("location")
    if not row:
        raise UnknownNameError(f"No location with id '{location_id}'.")
    item = location_item(row, directory)
    row = {**row, "children": row.get("children") or []}
    # An id and a path on every child, so two children with one name can be told apart and
    # passed back to get_location or a device filter.
    item["children"] = [_child_item(child, item["path"], directory) for child in row["children"]]
    for key in ("facility", "physical_address", "time_zone", "latitude", "longitude"):
        item[key] = row.get(key)
    return item


async def list_location_types(ctx: QueryContext) -> dict[str, Any]:
    """Location types and their hierarchy (for example Country > State > City)."""
    rows = await ctx.client.list_all("location_types", LOCATION_TYPE_SELECTION)
    items = [
        {
            "name": row["name"],
            "parent": (row.get("parent") or {}).get("name"),
            "nestable": row.get("nestable"),
        }
        for row in rows
    ]
    return envelope(items, None, offset=0, applied_filters={})


async def list_roles(ctx: QueryContext, *, content_type: str = "dcim.device") -> dict[str, Any]:
    """Role names for one object type (they differ per type)."""
    vocabulary = await ctx.vocabularies.get(roles_spec(content_type))
    return _name_list(vocabulary.names, content_type)


async def list_statuses(ctx: QueryContext, *, content_type: str = "dcim.device") -> dict[str, Any]:
    """Status names valid for one object type."""
    vocabulary = await ctx.vocabularies.get(statuses_spec(content_type))
    return _name_list(vocabulary.names, content_type)


async def list_tags(ctx: QueryContext, *, content_type: str = "dcim.device") -> dict[str, Any]:
    """Tag names that can be applied to one object type."""
    vocabulary = await ctx.vocabularies.get(tags_spec(content_type))
    return _name_list(vocabulary.names, content_type)


def _name_list(values: tuple[str, ...], content_type: str) -> dict[str, Any]:
    return envelope(
        [{"name": value} for value in values],
        None,
        offset=0,
        applied_filters={"content_type": content_type},
    )
