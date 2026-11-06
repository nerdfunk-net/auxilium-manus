"""The device attribute query keeps the MAC address of every interface.

``get-nautobot-attributes`` (group ``interfaces``) and ``get_device_attributes`` read the bag this
query fills; ``update-nautobot-device`` and the assistant rely on ``mac_address`` being in it.
"""

from __future__ import annotations

import re

import pytest

from services.nautobot.devices.attribute_bag import (
    CABLES_LAYOUT_LEGACY,
    CABLES_LAYOUT_V32,
    build_device_attributes_query,
)


def _block(query: str, opening: str) -> str:
    """The brace-balanced selection that starts at ``opening`` (e.g. the interfaces group)."""
    start = query.index(opening)
    depth = 0
    for position in range(query.index("{", start), len(query)):
        if query[position] == "{":
            depth += 1
        elif query[position] == "}":
            depth -= 1
            if depth == 0:
                return query[start : position + 1]
    raise AssertionError(f"unbalanced selection after {opening!r}")


@pytest.mark.parametrize("layout", [None, CABLES_LAYOUT_LEGACY, CABLES_LAYOUT_V32])
def test_the_interfaces_group_selects_the_mac_address(layout: str | None) -> None:
    query = build_device_attributes_query(layout)

    group = _block(query, "interfaces @include(if: $get_interfaces)")

    assert re.search(r"^\s*mac_address\s*$", group, re.MULTILINE)
    assert re.search(r"^\s*name\s*$", group, re.MULTILINE)  # the key the MAC is addressed by


@pytest.mark.parametrize("layout", [CABLES_LAYOUT_LEGACY, CABLES_LAYOUT_V32])
def test_the_cables_selection_is_a_separate_group_that_does_not_replace_the_interfaces_one(
    layout: str,
) -> None:
    query = build_device_attributes_query(layout)

    assert "interfaces @include(if: $get_cables)" in query
    assert "interfaces @include(if: $get_interfaces)" in query
