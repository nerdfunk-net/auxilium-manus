"""``scripts/check_branch_coverage.py`` (guard 11): the floor is a two-sided ratchet."""

from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "check_branch_coverage", _BACKEND / "scripts" / "check_branch_coverage.py"
)
assert _spec and _spec.loader
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


def _file(covered: int, total: int) -> dict:
    return {"summary": {"covered_branches": covered, "num_branches": total}}


def test_the_percent_is_summed_over_all_files() -> None:
    files = {"a.py": _file(1, 4), "b.py": _file(8, 6 + 10)}

    assert guard.branch_percent(files) == pytest.approx(100 * 9 / 20)


def test_no_branch_data_is_an_error_not_a_pass() -> None:
    with pytest.raises(ValueError, match="branch = true"):
        guard.branch_percent({"a.py": _file(0, 0)})


@pytest.mark.parametrize("actual", [90.0, 90.5, 90.99])
def test_inside_the_window_passes(actual: float) -> None:
    assert guard.verdict(actual, floor=90.0) is None


@pytest.mark.parametrize("actual", [89.99, 50.0])
def test_below_the_floor_fails(actual: float) -> None:
    assert "below the floor" in guard.verdict(actual, floor=90.0)


@pytest.mark.parametrize("actual", [91.0, 99.0])
def test_far_above_the_floor_asks_to_raise_it(actual: float) -> None:
    assert "raise BRANCH_FLOOR" in guard.verdict(actual, floor=90.0)


def test_a_missing_data_file_fails(tmp_path: Path) -> None:
    assert guard.main([str(tmp_path / ".coverage")]) == 1


def test_the_suite_records_branches() -> None:
    config = tomllib.loads((_BACKEND / "pyproject.toml").read_text())

    assert config["tool"]["coverage"]["run"]["branch"] is True
