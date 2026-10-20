"""workflow_steps.common.step_flags: bool flag parsing and dry-run recording."""

from __future__ import annotations

import pytest

from models.workflow_context import DeviceContext, DeviceStatus
from workflow_steps.common.step_flags import parse_bool_flag, parse_int_flag, record_dry_run


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (False, False),
        ("true", True),
        (" YES ", True),
        ("on", True),
        ("1", True),
        ("0", False),
        ("off", False),
        ("", False),
        (1, True),
        (0, False),
        (None, False),
    ],
)
def test_parse_bool_flag_values(value, expected) -> None:
    assert parse_bool_flag({"flag": value}, "flag") is expected


def test_missing_key_uses_default() -> None:
    assert parse_bool_flag({}, "flag") is False
    assert parse_bool_flag({}, "flag", default=True) is True


def _device(**overrides) -> DeviceContext:
    return DeviceContext(id="d1", name="r1", hostname="r1", **overrides)


def test_record_dry_run_keeps_other_nodes_and_sets_ok() -> None:
    device = _device(status=DeviceStatus.FAILED, dry_run_results={"other": {"x": 1}})

    updated = record_dry_run(device, node_id="n1", payload={"would": "run"})

    assert updated.status == DeviceStatus.OK
    assert updated.dry_run_results == {"other": {"x": 1}, "n1": {"would": "run"}}


def test_record_dry_run_does_not_mutate_the_input() -> None:
    device = _device(dry_run_results={"other": {"x": 1}})

    record_dry_run(device, node_id="n1", payload={"would": "run"})

    assert device.dry_run_results == {"other": {"x": 1}}


def test_string_false_is_false() -> None:
    for text in ("false", "FALSE", " no ", "0", "off", ""):
        assert parse_bool_flag({"x": text}, "x", default=True) is False


def test_string_true_is_true() -> None:
    for text in ("true", "True", "1", "yes", "on"):
        assert parse_bool_flag({"x": text}, "x") is True


def test_real_booleans_and_numbers() -> None:
    assert parse_bool_flag({"x": True}, "x") is True
    assert parse_bool_flag({"x": False}, "x", default=True) is False
    assert parse_bool_flag({"x": 0}, "x", default=True) is False
    assert parse_bool_flag({"x": 2}, "x") is True


def test_unknown_string_raises_with_key_name() -> None:
    with pytest.raises(ValueError, match="dry_run must be true or false"):
        parse_bool_flag({"dry_run": "ture"}, "dry_run")


def test_none_and_missing_use_default() -> None:
    assert parse_bool_flag({"x": None}, "x", default=True) is True
    assert parse_bool_flag({}, "x", default=True) is True
    assert parse_bool_flag({}, "x") is False


def test_int_flag_empty_string_uses_default() -> None:
    assert parse_int_flag({"n": ""}, "n", default=5) == 5
    assert parse_int_flag({"n": None}, "n", default=5) == 5
    assert parse_int_flag({}, "n", default=5) == 5
    assert parse_int_flag({"n": "7"}, "n", default=5) == 7


def test_int_flag_bounds_and_errors() -> None:
    with pytest.raises(ValueError, match="between 1 and 10"):
        parse_int_flag({"n": 0}, "n", default=1, minimum=1, maximum=10)
    with pytest.raises(ValueError, match="between 1 and 10"):
        parse_int_flag({"n": 11}, "n", default=1, minimum=1, maximum=10)
    with pytest.raises(ValueError, match="chunk_size must be a whole number"):
        parse_int_flag({"chunk_size": "abc"}, "chunk_size", default=1)
    with pytest.raises(ValueError, match="whole number"):
        parse_int_flag({"n": True}, "n", default=1)


def test_parse_int_flag_refuses_a_fractional_float() -> None:
    with pytest.raises(ValueError):
        parse_int_flag({"n": 1.9}, "n", default=1)


def test_parse_int_flag_accepts_an_integral_float() -> None:
    assert parse_int_flag({"n": 2.0}, "n", default=1) == 2
