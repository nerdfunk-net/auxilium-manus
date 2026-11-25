"""The shared parsers of the controller steps: ``max_devices`` and the fact/topology selectors."""

from __future__ import annotations

import pytest

from workflow_steps.common.controller_inventory import MAX_DEVICES_CEILING, parse_max_devices
from workflow_steps.common.fact_entries import parse_name_list

_ALLOWED = ("device", "software", "interfaces")
_DEFAULT = ("device",)


def _names(raw: object) -> tuple[str, ...]:
    return parse_name_list(
        raw, step_id="step-x", key="facts", noun="fact", allowed=_ALLOWED, default=_DEFAULT
    )


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_a_blank_max_devices_means_no_cap(raw: object) -> None:
    assert parse_max_devices(raw, step_id="step-x") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(1, 1), ("25", 25), (" 7 ", 7), (MAX_DEVICES_CEILING, MAX_DEVICES_CEILING)],
)
def test_max_devices_accepts_a_whole_number_in_range(raw: object, expected: int) -> None:
    assert parse_max_devices(raw, step_id="step-x") == expected


@pytest.mark.parametrize(
    "raw", [0, -1, MAX_DEVICES_CEILING + 1, True, 1.5, "x", "1.5", "-3", [1], {}]
)
def test_max_devices_outside_the_range_is_a_config_error(raw: object) -> None:
    with pytest.raises(
        ValueError,
        match=rf"^step-x: max_devices must be a whole number between 1 and {MAX_DEVICES_CEILING}$",
    ):
        parse_max_devices(raw, step_id="step-x")


def test_no_list_means_the_default() -> None:
    assert _names(None) == _DEFAULT


def test_the_names_come_back_in_the_canonical_order() -> None:
    assert _names(["interfaces", "device"]) == ("device", "interfaces")


@pytest.mark.parametrize("raw", ["device", ["device", 1], {"device": True}, 3])
def test_a_value_that_is_not_a_list_of_strings_is_refused(raw: object) -> None:
    with pytest.raises(ValueError, match=r"^step-x: facts must be a list of fact names$"):
        _names(raw)


def test_an_unknown_name_is_refused_with_the_choices() -> None:
    expected = (
        "step-x: unknown fact(s) ['b', 'z']; "
        "choose from ['device', 'software', 'interfaces']"
    )
    with pytest.raises(ValueError) as info:
        _names(["z", "device", "b"])
    assert str(info.value) == expected


def test_an_empty_list_is_refused() -> None:
    with pytest.raises(ValueError, match=r"^step-x: select at least one fact$"):
        _names([])
