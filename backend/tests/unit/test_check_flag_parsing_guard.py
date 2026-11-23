"""The AST rules of ``scripts/check_flag_parsing.py`` (guard 1, W11-07/W13-10)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_flag_parsing.py"
_spec = importlib.util.spec_from_file_location("check_flag_parsing", _SCRIPT)
assert _spec and _spec.loader
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


def _hits(source: str) -> list[str]:
    return [message for _line, message in guard.violations_in(source)]


@pytest.mark.parametrize(
    ("source", "fragment"),
    [
        ('x = bool(config.get("a"))', "parse_bool_flag"),
        ("x = bool(config.get(key, True))", "parse_bool_flag"),
        ('x = int(config.get("n"))', "parse_int_flag"),
        ("x = int(merged_config.get(key))", "parse_int_flag"),
        ("x = float(cfg.get(key, 1))", "parse_int_flag"),
        ("x = int(raw_repository_id)", "parse_repository_id"),
        ('x = int(config["git_repository_id"])', "parse_repository_id"),
        ('x = config.get("a") is True', "parse_bool_flag"),
        ('x = value.strip().lower() in {"1", "true", "yes", "on"}', "spelling table"),
        ('x = value.strip().lower() not in ("0", "false")', "spelling table"),
        ("def _parse_bool(v): ...", "private boolean parser"),
    ],
)
def test_the_rule_flags_the_lax_form(source: str, fragment: str) -> None:
    hits = _hits(source)

    assert len(hits) == 1 and fragment in hits[0]


@pytest.mark.parametrize(
    "source",
    [
        'x = parse_bool_flag(config, "a", default=True)',
        'x = parse_int_flag(config, "n", default=3)',
        "x = parse_repository_id(raw_repository_id, step_id=s)",
        "x = int(text)  # a plain int() of a value that is not config",
        'x = value in {"a", "b"}',
        'x = os.environ.get("FLAG")',
    ],
)
def test_the_rule_leaves_the_strict_forms_alone(source: str) -> None:
    assert _hits(source) == []


def test_the_opt_out_comment_silences_one_line() -> None:
    source = 'x = value.strip().lower() in {"true"}  # check_flag_parsing: ok - resolved value\n'

    assert _hits(source) == []


def test_the_tree_is_clean() -> None:
    assert guard.main([]) == 0
