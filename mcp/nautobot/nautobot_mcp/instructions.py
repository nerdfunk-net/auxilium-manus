"""The server ``instructions`` shown to the model, built from the live vocabulary."""

from __future__ import annotations

import logging

from nautobot_mcp.client import NautobotError
from nautobot_mcp.vocabularies import (
    LOCATION_TYPES_SPEC,
    VocabularyCache,
    roles_spec,
    statuses_spec,
)

logger = logging.getLogger(__name__)

_HOW_TO_USE = """\
Read-only access to a Nautobot network source of truth.
Names are matched case-insensitively. If a name is not found the error shows the Closest
match and the available names: retry with one of them. If unsure what a word means in this
instance (for example whether "router" is a role, a device type or a platform), call
list_roles, list_statuses, list_location_types or list_tags first. Location names are not
unique: use the 'Parent → Name' path or the id when a name is ambiguous. Filtering by a
location includes its child locations. Results are paged: when has_more is true, repeat the
call with a larger offset."""

FALLBACK_INSTRUCTIONS = (
    _HOW_TO_USE + "\n\n(The live vocabulary could not be loaded at startup; call list_roles, "
    "list_statuses and list_location_types to discover the names used by this instance.)"
)


MAX_NAME_CHARS = 60


def _listed(names: list[str]) -> str:
    """Names copied into the prompt; any name with control characters or odd length is dropped.

    Nautobot users can rename roles, statuses and location types, and the instructions are
    trusted guidance for the model, so a name must not be able to start a new line or carry text.
    """
    safe = [n for n in names if n.isprintable() and 0 < len(n) <= MAX_NAME_CHARS]
    return ", ".join(safe)


async def build_instructions(vocabularies: VocabularyCache) -> str:
    """Describe this instance's vocabulary; fall back to a static text if Nautobot is down."""
    try:
        roles = await vocabularies.get(roles_spec("dcim.device"))
        statuses = await vocabularies.get(statuses_spec("dcim.device"))
        location_types = await vocabularies.get(LOCATION_TYPES_SPEC)
        locations = await vocabularies.locations()
    except NautobotError as exc:
        logger.warning("Could not load the vocabulary for the instructions: %s", exc)
        return FALLBACK_INSTRUCTIONS
    return (
        f"{_HOW_TO_USE}\n\nThis instance:\n"
        f"- Device roles: {_listed(roles.names)}\n"
        f"- Device statuses: {_listed(statuses.names)}\n"
        f"- Location types: {_listed(location_types.names)}\n"
        f"- {len(locations.records)} locations (use list_locations to browse them)"
    )
