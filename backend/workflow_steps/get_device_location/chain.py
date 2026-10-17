"""Pure helpers for reading a device's location hierarchy from Nautobot GraphQL."""

from __future__ import annotations

from typing import Any

# Levels of the hierarchy read per device (leaf included). Nautobot hierarchies are bounded
# by their location-type tree, which is far shallower than this.
LOCATION_CHAIN_DEPTH = 8


def _build_query(depth: int) -> str:
    # The innermost level also selects ``parent { name }``: a present parent there means the
    # hierarchy continues beyond the depth read, an absent one means that level is the root.
    inner = "name location_type { name } parent { name }"
    for _ in range(depth - 1):
        inner = f"name location_type {{ name }} parent {{ {inner} }}"
    return "query ($deviceId: ID!) { device(id: $deviceId) { location { " + inner + " } } }"


LOCATION_CHAIN_QUERY = _build_query(LOCATION_CHAIN_DEPTH)


def _walk(location: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Nodes leaf to root; one extra node past the depth means the chain was cut off."""
    chain: list[dict[str, Any]] = []
    current = location
    while isinstance(current, dict) and len(chain) <= LOCATION_CHAIN_DEPTH:
        chain.append(current)
        parent = current.get("parent")
        current = parent if isinstance(parent, dict) else None
    return chain


def _type_name(node: dict[str, Any]) -> str | None:
    location_type = node.get("location_type")
    if isinstance(location_type, dict):
        name = location_type.get("name")
        return str(name) if name else None
    return None


def find_locations_by_type(location: dict[str, Any] | None, type_name: str) -> list[str]:
    """Names of every location in the chain whose location type is *type_name* (exact match).

    More than one entry happens only for a nestable location type (a Building inside a
    Building); the caller decides what that means. Locations without a name are skipped.
    """
    return [
        str(node["name"])
        for node in _walk(location)[:LOCATION_CHAIN_DEPTH]
        if _type_name(node) == type_name and node.get("name")
    ]


def describe_chain(location: dict[str, Any] | None) -> str:
    """Human-readable chain, leaf to root, for error messages."""
    chain = _walk(location)
    if not chain:
        return "no location"
    shown = chain[:LOCATION_CHAIN_DEPTH]
    text = " -> ".join(f"{node.get('name')} ({_type_name(node) or '?'})" for node in shown)
    if len(chain) > LOCATION_CHAIN_DEPTH:
        text += f" -> ... (hierarchy cut off after {LOCATION_CHAIN_DEPTH} levels)"
    return text
