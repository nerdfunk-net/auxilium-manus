"""The list_devices example handler (feeds the Get from Agent step)."""

from __future__ import annotations

import pytest

from handlers.examples import list_devices


def test_returns_the_devices_of_the_site() -> None:
    answer = list_devices({}, {"attributes": {"site": " Berlin "}})
    assert [d["name"] for d in answer["devices"]] == ["ber-sw01", "ber-sw02"]
    assert set(answer["devices"][0]) == {"name", "ip_address", "network_driver"}


def test_unknown_site_gives_an_empty_list() -> None:
    assert list_devices({}, {"attributes": {"site": "rome"}}) == {"devices": []}


def test_site_is_required() -> None:
    with pytest.raises(ValueError, match="site"):
        list_devices({}, {"attributes": {}})


@pytest.mark.parametrize("attributes", [None, [], "site", {}])
def test_malformed_attributes_are_a_clean_error(attributes) -> None:
    with pytest.raises(ValueError, match="site"):
        list_devices({}, {"attributes": attributes})
