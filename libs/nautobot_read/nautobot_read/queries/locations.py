"""Finding locations, with or without the whole location tree.

The tree (``LocationDirectory``) gives ``Parent → Name`` paths and resolves names and paths. It
is loaded whole, so a Nautobot with more locations than ``list_all`` collects cannot have one.
A query that only needs a location for a filter or a label must still work then: it falls back
to a direct lookup by exact name (or id) and to the plain name as the label.
"""

from __future__ import annotations

from nautobot_read.client import TooManyRowsError
from nautobot_read.context import QueryContext
from nautobot_read.networks import InvalidInputError
from nautobot_read.vocabularies import PATH_SEPARATOR, AmbiguousNameError, LocationDirectory
from nautobot_read.vocabulary import UUID_PATTERN, UnknownNameError

MAX_NAME_MATCHES = 6
LOOKUP_SELECTION = "id name location_type { name } parent { name }"


async def directory_or_none(ctx: QueryContext) -> LocationDirectory | None:
    """The location tree, or ``None`` when it is too large to load (other failures propagate)."""
    try:
        return await ctx.vocabularies.locations()
    except TooManyRowsError:
        return None


def path_or_name(directory: LocationDirectory | None, location_id: str, name: str | None) -> str:
    """``Parent → Name`` when the tree is known, else the plain name."""
    return (directory.path_of(location_id) if directory else "") or name or ""


async def resolve_location(
    ctx: QueryContext, value: str, directory: LocationDirectory | None
) -> tuple[str, str]:
    """``(id, label)`` of the location meant by ``value`` (name, ``A → B`` path or id)."""
    if directory is not None:
        record = directory.resolve(value)
        return record.id, record.path
    text = value.strip()
    if UUID_PATTERN.match(text):
        return text.lower(), text.lower()
    if PATH_SEPARATOR.strip() in text or ">" in text:
        raise InvalidInputError(
            "This Nautobot has too many locations to browse as a tree, so a 'Parent → Name' path "
            "cannot be resolved: give the location name, or its id."
        )
    page = await ctx.client.list_page(
        "locations", LOOKUP_SELECTION, {"name": [text]}, limit=MAX_NAME_MATCHES, offset=0
    )
    if not page.items:
        raise UnknownNameError(
            f"No location '{text}'. Names must match exactly; use list_locations with "
            "name_contains to search."
        )
    if len(page.items) > 1:
        listing = "; ".join(
            f"{row['name']} ({(row.get('location_type') or {}).get('name')}, under "
            f"{(row.get('parent') or {}).get('name') or 'the top level'}, id {row['id']})"
            for row in page.items
        )
        total = f"at least {len(page.items)}" if page.has_more else str(len(page.items))
        raise AmbiguousNameError(
            f"'{text}' matches {total} locations: {listing}. Retry with the id."
        )
    return page.items[0]["id"], page.items[0]["name"]
