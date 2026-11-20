"""Location lists of objects that have several locations (VLANs, prefixes).

Nautobot 3 exposes ``locations`` read-only on such an object (a PATCH of it is silently ignored);
the set is the rows of an assignment endpoint, one per object and location (for example
``ipam/vlan-location-assignments/`` with ``vlan`` and ``location``). These helpers read and change
those rows for any such object.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Literal

from services.nautobot.common.rest import rest_paginate, rest_query
from services.nautobot.common.validators import is_valid_uuid

from ..common.exceptions import NautobotAPIError

if TYPE_CHECKING:
    from services.nautobot.api_protocol import NautobotApi

logger = logging.getLogger(__name__)

LocationsMode = Literal["replace", "add", "remove"]
LOCATIONS_MODES: tuple[str, ...] = ("replace", "add", "remove")


class PartialUpdateError(NautobotAPIError):
    """A write failed after earlier writes had already been stored.

    ``applied`` names what is stored (``"fields"``, ``"locations"``); the original error is the
    ``__cause__``. Nautobot has no transaction across the calls, so a second run completes it.
    """

    def __init__(self, applied: Sequence[str]) -> None:
        super().__init__("Update stopped part-way: " + ", ".join(applied) + " already written")
        self.applied = tuple(applied)


def reference_id(value: object) -> object:
    """A related object arrives as a UUID or as a nested object; compare by its id."""
    return value.get("id") if isinstance(value, dict) else value


def merge_locations(
    current: Sequence[str], requested: Sequence[str], mode: LocationsMode
) -> list[str]:
    """The location ids an object has after applying ``requested`` in ``mode``."""
    if mode == "replace":
        return list(dict.fromkeys(requested))
    if mode == "add":
        return list(dict.fromkeys([*current, *requested]))
    drop = set(requested)
    return [item for item in current if item not in drop]


async def _assigned(
    nautobot: NautobotApi, endpoint: str, owner_field: str, owner_id: str
) -> dict[str, list[str]]:
    """Location id -> the assignment row ids of one object (a location can have several rows)."""
    query = rest_query(**{owner_field: owner_id, "limit": 1000, "format": "json"})
    rows = await rest_paginate(nautobot, f"{endpoint}?{query}")
    assigned: dict[str, list[str]] = {}
    for row in rows:
        assigned.setdefault(str(reference_id(row.get("location"))), []).append(str(row.get("id")))
    return assigned


def _uuid_row_ids(row_ids: Sequence[str]) -> list[str]:
    """The row ids that are about to be put in a DELETE path; each must be a UUID.

    The ids come from Nautobot's answer. One like ``../../dcim/devices/<uuid>`` would otherwise
    make the DELETE hit another object, so an id that is not a UUID stops the whole change.
    """
    for row_id in row_ids:
        if not is_valid_uuid(row_id.lower()):
            raise NautobotAPIError("Nautobot answered with an assignment id that is not a UUID")
    return list(row_ids)


async def missing_locations(
    nautobot: NautobotApi,
    endpoint: str,
    owner_field: str,
    owner_id: str,
    locations: Sequence[str],
) -> list[str]:
    """The ids in ``locations`` the object is not assigned to yet (a read; nothing is written)."""
    assigned = await _assigned(nautobot, endpoint, owner_field, owner_id)
    return [item for item in dict.fromkeys(locations) if item not in assigned]


async def apply_locations(
    nautobot: NautobotApi,
    endpoint: str,
    owner_field: str,
    owner_id: str,
    requested: Sequence[str],
    mode: LocationsMode,
) -> bool:
    """Create / delete assignments so the object's locations match; True if any changed.

    Raises:
        PartialUpdateError: If a write failed after another one was stored.
    """
    if not requested:
        return False
    for location in requested:
        if not is_valid_uuid(location.lower()):
            raise ValueError("a location is not a Nautobot UUID")
    assigned = await _assigned(nautobot, endpoint, owner_field, owner_id)
    wanted = merge_locations(list(assigned), requested, mode)
    to_add = [location for location in wanted if location not in assigned]
    # Every row of a location that goes (Nautobot allows no duplicates, but a lookup must not
    # trust that); checked before the first write so a bad answer changes nothing.
    to_remove = _uuid_row_ids(
        [row_id for location, rows in assigned.items() if location not in wanted for row_id in rows]
    )
    written = 0
    try:
        for location in to_add:
            await nautobot.rest_request(
                endpoint=endpoint,
                method="POST",
                data={owner_field: owner_id, "location": location},
            )
            written += 1
        for row_id in to_remove:
            await nautobot.rest_request(endpoint=f"{endpoint}{row_id}/", method="DELETE")
            written += 1
    except Exception as exc:
        if written:
            raise PartialUpdateError(["locations"]) from exc
        raise
    if to_add or to_remove:
        logger.info(
            "%s %s locations added=%d removed=%d",
            owner_field,
            owner_id,
            len(to_add),
            len(to_remove),
        )
    return bool(to_add or to_remove)
