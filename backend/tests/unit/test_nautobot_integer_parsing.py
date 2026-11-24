"""Hand-rolled integer parsing of resolved per-device values (P-T write-first for W5-11).

One device whose attribute holds a superscript digit must fail that device, not the step.
"""

from __future__ import annotations

import pytest

from tests.unit._step_helpers import make_device
from workflow_steps.add_nautobot_metadata.executor import _DeviceFailure, _parse_height
from workflow_steps.common.nautobot_object_update import plan_device
from workflow_steps.update_nautobot_vlan.executor import _SPEC, _parse_config, _request


def _plan(vid: str):  # noqa: ANN202
    parsed = _parse_config(
        {"nautobot_source_id": "src", "vid": vid, "name": "v", "locations_mode": "add"}
    )
    return plan_device(_SPEC, _request(parsed), make_device("d1"), "run-1")


def test_a_plain_vid_is_planned() -> None:
    plan = _plan("100")

    assert plan.key == "100"


@pytest.mark.parametrize("vid", ["0", "4095", "abc", "1.5", "-3"])
def test_an_out_of_range_or_non_numeric_vid_fails_the_device(vid: str) -> None:
    result = _plan(vid)

    assert result[0] == "vid_invalid"


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


@pytest.mark.parametrize("text", ["1_0", "١٠"])
def test_height_refuses_underscores_and_non_ascii_digits(text: str) -> None:
    with pytest.raises(_DeviceFailure):
        _parse_height(text)


# ── add-to-nautobot: rack position and virtual-chassis mode ────────────────────────────────────


@pytest.mark.parametrize(("text", "expected"), [("5", 5), (" 12 ", 12), ("", None), (None, None)])
def test_position_takes_digits_or_nothing(text: object, expected: int | None) -> None:
    from workflow_steps.add_to_nautobot.executor import _position_as_int

    assert _position_as_int(text) == expected


@pytest.mark.parametrize("text", ["abc", "1_0", "²", "١٠", "1.5", "-1"])
def test_a_bad_position_fails_the_device_instead_of_being_dropped(text: str) -> None:
    from workflow_steps.add_to_nautobot.executor import _position_as_int, _PositionError

    with pytest.raises(_PositionError):
        _position_as_int(text)


def test_add_to_nautobot_reads_its_flags_once_and_refuses_a_typo() -> None:
    from workflow_steps.add_to_nautobot.executor import _parse_config

    base = {"nautobot_source_id": "src"}

    parsed = _parse_config({**base, "add_prefix": "false", "dry_run": "yes"})

    assert parsed.add_prefix is False and parsed.dry_run is True
    with pytest.raises(ValueError, match="add_prefix must be true or false"):
        _parse_config({**base, "add_prefix": "banana"})


def test_an_unknown_virtual_chassis_mode_is_refused() -> None:
    from workflow_steps.add_to_nautobot.executor import _parse_config

    with pytest.raises(ValueError, match="virtual_chassis.mode must be one of"):
        _parse_config({"nautobot_source_id": "src", "virtual_chassis": {"mode": "creat"}})

    parsed = _parse_config(
        {"nautobot_source_id": "src", "virtual_chassis": {"mode": "join", "id": " vc1 "}}
    )
    assert parsed.virtual_chassis_id == "vc1" and parsed.virtual_chassis_name is None
