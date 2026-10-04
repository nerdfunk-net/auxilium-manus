"""workflow_steps.common.step_flags: bool flag parsing and dry-run recording."""

from __future__ import annotations

import pytest

from models.workflow_context import DeviceContext, DeviceStatus
from workflow_steps.common.step_flags import parse_bool_flag, record_dry_run


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
