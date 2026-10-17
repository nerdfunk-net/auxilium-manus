"""Tests for workflow_steps/get_device_location/chain.py."""

from __future__ import annotations

import unittest

from workflow_steps.get_device_location.chain import (
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


class FindLocationByTypeTests(unittest.TestCase):
    def test_matches_leaf(self) -> None:
        self.assertEqual(find_locations_by_type(_room(), "Room"), ["Room A"])

    def test_matches_middle(self) -> None:
        self.assertEqual(find_locations_by_type(_room(), "City"), ["City A"])

    def test_matches_root(self) -> None:
        self.assertEqual(find_locations_by_type(_room(), "Country"), ["Country A"])

    def test_no_match(self) -> None:
        self.assertEqual(find_locations_by_type(_room(), "Continent"), [])

    def test_location_none(self) -> None:
        self.assertEqual(find_locations_by_type(None, "City"), [])

    def test_missing_location_type_is_skipped(self) -> None:
        loc = _node("X", None, _node("Y", "City"))
        self.assertEqual(find_locations_by_type(loc, "City"), ["Y"])

    def test_match_is_case_sensitive(self) -> None:
        self.assertEqual(find_locations_by_type(_room(), "city"), [])


class DescribeChainTests(unittest.TestCase):
    def test_lists_leaf_to_root(self) -> None:
        self.assertEqual(
            describe_chain(_room()),
            "Room A (Room) -> Building A (Building) -> City A (City) "
            "-> State A (State) -> Country A (Country)",
        )

    def test_empty(self) -> None:
        self.assertEqual(describe_chain(None), "no location")


class NestableTests(unittest.TestCase):
    def test_same_type_twice_returns_both_leaf_first(self) -> None:
        loc = _node("Inner", "Building", _node("Outer", "Building", _node("C", "City")))
        self.assertEqual(find_locations_by_type(loc, "Building"), ["Inner", "Outer"])

    def test_nameless_hit_does_not_hide_named_parent(self) -> None:
        loc = _node("", "Building", _node("Outer", "Building"))
        self.assertEqual(find_locations_by_type(loc, "Building"), ["Outer"])


def _deep(levels: int, *, sentinel: bool) -> dict | None:
    """A chain of *levels* typed nodes; with *sentinel* the GraphQL ``parent { name }`` node."""
    node: dict | None = {"name": "beyond", "parent": None} if sentinel else None
    for level in range(levels, 0, -1):
        node = _node(f"L{level}", f"T{level}", node)
    return node


class TruncationTests(unittest.TestCase):
    def test_hierarchy_deeper_than_cap_is_flagged_and_sentinel_never_matches(self) -> None:
        node = _deep(LOCATION_CHAIN_DEPTH, sentinel=True)
        self.assertIn("cut off", describe_chain(node))
        self.assertEqual(find_locations_by_type(node, "beyond"), [])

    def test_exact_depth_without_sentinel_is_not_flagged(self) -> None:
        self.assertNotIn("cut off", describe_chain(_deep(LOCATION_CHAIN_DEPTH, sentinel=False)))

    def test_shallow_chain_is_not_flagged(self) -> None:
        self.assertNotIn("cut off", describe_chain(_deep(3, sentinel=False)))


class QueryTests(unittest.TestCase):
    def test_query_nests_to_depth_and_selects_only_names(self) -> None:
        self.assertEqual(LOCATION_CHAIN_QUERY.count("parent {"), LOCATION_CHAIN_DEPTH)
        self.assertEqual(LOCATION_CHAIN_QUERY.count("location_type {"), LOCATION_CHAIN_DEPTH)
        self.assertIn("$deviceId", LOCATION_CHAIN_QUERY)
        self.assertIn("location_type", LOCATION_CHAIN_QUERY)
