"""Hand-rolled integer parsing of resolved per-device values (P-T write-first for W5-11).

One device whose attribute holds a superscript digit must fail that device, not the step.
"""

from __future__ import annotations

import pytest

from tests.unit._step_helpers import make_device, strict_xfail
from workflow_steps.add_nautobot_metadata.executor import _DeviceFailure, _parse_height
from workflow_steps.update_nautobot_vlan.executor import _parse_config, _plan_device


def _plan(vid: str):  # noqa: ANN202
    parsed = _parse_config(
        {"nautobot_source_id": "src", "vid": vid, "name": "v", "locations_mode": "add"}
    )
    return _plan_device(parsed, make_device("d1"), "run-1")


def test_a_plain_vid_is_planned() -> None:
    plan = _plan("100")

    assert plan.vid == 100


@pytest.mark.parametrize("vid", ["0", "4095", "abc", "1.5", "-3"])
def test_an_out_of_range_or_non_numeric_vid_fails_the_device(vid: str) -> None:
    result = _plan(vid)

    assert result[0] == "vid_invalid"


@strict_xfail("W5-11", "'²'.isdigit() is True and int('²') raises: the step aborts")
def test_a_superscript_digit_in_vid_fails_the_device_not_the_step() -> None:
    result = _plan("²")

    assert result[0] == "vid_invalid"


@pytest.mark.parametrize("text", ["10", " 42 "])
def test_height_takes_a_positive_whole_number(text: str) -> None:
    assert _parse_height(text) == int(text)


@pytest.mark.parametrize("text", ["0", "-1", "abc", "1.0", "True", ""])
def test_height_refuses_everything_else(text: str) -> None:
    with pytest.raises(_DeviceFailure):
        _parse_height(text)


@strict_xfail("W5-11", "int() accepts underscores and non-ASCII digits")
@pytest.mark.parametrize("text", ["1_0", "١٠"])
def test_height_refuses_underscores_and_non_ascii_digits(text: str) -> None:
    with pytest.raises(_DeviceFailure):
        _parse_height(text)
