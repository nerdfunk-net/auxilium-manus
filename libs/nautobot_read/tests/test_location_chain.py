"""A device's location chain: the query text and its walk (from the get-device-location step)."""

from nautobot_read.location_chain import (
    LOCATION_CHAIN_DEPTH,
    LOCATION_CHAIN_QUERY,
    describe_chain,
    find_locations_by_type,
)


def _node(name: str, type_name: str | None, parent: dict | None = None) -> dict:
    return {
        "name": name,
        "location_type": {"name": type_name} if type_name else None,
        "parent": parent,
    }


def _room() -> dict:
    country = _node("Country A", "Country")
    city = _node("City A", "City", _node("State A", "State", country))
    return _node("Room A", "Room", _node("Building A", "Building", city))


def _deep(levels: int, *, sentinel: bool) -> dict | None:
    """A chain of *levels* typed nodes; with *sentinel* the GraphQL ``parent { name }`` node."""
    node: dict | None = {"name": "beyond", "parent": None} if sentinel else None
    for level in range(levels, 0, -1):
        node = _node(f"L{level}", f"T{level}", node)
    return node


def test_matches_leaf_middle_and_root():
    assert find_locations_by_type(_room(), "Room") == ["Room A"]
    assert find_locations_by_type(_room(), "City") == ["City A"]
    assert find_locations_by_type(_room(), "Country") == ["Country A"]


def test_no_match_and_no_location():
    assert find_locations_by_type(_room(), "Continent") == []
    assert find_locations_by_type(None, "City") == []


def test_a_level_without_a_type_name_is_skipped():
    assert find_locations_by_type(_node("X", None, _node("Y", "City")), "City") == ["Y"]
    nameless_type = {"name": "Z", "location_type": {"name": ""}, "parent": _node("Y", "City")}
    assert find_locations_by_type(nameless_type, "City") == ["Y"]
    assert describe_chain(nameless_type) == "Z (?) -> Y (City)"


def test_match_is_case_sensitive():
    assert find_locations_by_type(_room(), "city") == []


def test_describe_lists_leaf_to_root():
    assert describe_chain(_room()) == (
        "Room A (Room) -> Building A (Building) -> City A (City) "
        "-> State A (State) -> Country A (Country)"
    )
    assert describe_chain(None) == "no location"


def test_a_nestable_type_returns_every_level_leaf_first():
    loc = _node("Inner", "Building", _node("Outer", "Building", _node("C", "City")))
    assert find_locations_by_type(loc, "Building") == ["Inner", "Outer"]


def test_a_nameless_hit_does_not_hide_a_named_parent():
    loc = _node("", "Building", _node("Outer", "Building"))
    assert find_locations_by_type(loc, "Building") == ["Outer"]


def test_a_hierarchy_deeper_than_the_cap_is_flagged_and_the_sentinel_never_matches():
    node = _deep(LOCATION_CHAIN_DEPTH, sentinel=True)
    assert "cut off" in describe_chain(node)
    assert find_locations_by_type(node, "beyond") == []


def test_a_chain_at_or_below_the_cap_is_not_flagged():
    assert "cut off" not in describe_chain(_deep(LOCATION_CHAIN_DEPTH, sentinel=False))
    assert "cut off" not in describe_chain(_deep(3, sentinel=False))


def test_the_query_nests_to_the_depth_and_selects_only_names():
    assert LOCATION_CHAIN_QUERY.count("parent {") == LOCATION_CHAIN_DEPTH
    assert LOCATION_CHAIN_QUERY.count("location_type {") == LOCATION_CHAIN_DEPTH
    assert "$deviceId" in LOCATION_CHAIN_QUERY


def test_eight_levels_are_read():
    assert LOCATION_CHAIN_DEPTH == 8


def test_a_level_past_the_depth_is_never_matched():
    # more typed levels than the query reads (a caller's own deeper data): only 8 count
    node = _deep(LOCATION_CHAIN_DEPTH + 1, sentinel=False)
    assert find_locations_by_type(node, f"T{LOCATION_CHAIN_DEPTH}") == [f"L{LOCATION_CHAIN_DEPTH}"]
    assert find_locations_by_type(node, f"T{LOCATION_CHAIN_DEPTH + 1}") == []
