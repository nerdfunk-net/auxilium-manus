"""The flag-parsing guard is a ratchet: zero violations in the tree, and it catches the patterns."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import check_flag_parsing  # noqa: E402


def test_tree_has_no_violations() -> None:
    assert check_flag_parsing.main([]) == 0


def test_bool_of_config_get_is_flagged() -> None:
    source = 'def f(config):\n    return bool(config.get("a", True))\n'
    assert len(check_flag_parsing.violations_in(source)) == 1


def test_is_true_comparison_is_flagged() -> None:
    source = 'def f(cfg):\n    return cfg.get("a") is True\n'
    assert len(check_flag_parsing.violations_in(source)) == 1


def test_private_parser_is_flagged() -> None:
    source = "def _parse_bool(value):\n    return bool(value)\n"
    assert len(check_flag_parsing.violations_in(source)) == 1


def test_clean_code_passes() -> None:
    source = 'def f(config):\n    return parse_bool_flag(config, "a")\n'
    assert check_flag_parsing.violations_in(source) == []
