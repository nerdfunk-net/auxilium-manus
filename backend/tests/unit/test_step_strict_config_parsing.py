"""Strict parsing of step flags and repository ids (P-T "write first" for P-A, W11-07).

Tests marked ``strict_xfail`` document today's lax parsing: they fail on the current code and
pass once P-A moves the site to ``step_flags`` / ``parse_repository_id``. Plain tests pin the
behaviour that must not change.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from tests.unit._step_helpers import call_step, make_context, make_device, make_run, strict_xfail
from workflow_steps.common.git_repository_loader import parse_repository_id

_LAX_ID = strict_xfail("W11-07", "int() accepts True and 7.9 as repository 1 and 7")


# ── the reference parser stays strict ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw", [True, 7.9, "abc", "7.9"])
def test_parse_repository_id_refuses_what_int_would_mangle(raw: Any) -> None:
    with pytest.raises(ValueError, match="whole number"):
        parse_repository_id(raw, step_id="s")


@pytest.mark.parametrize(
    ("raw", "expected"), [(7, 7), ("7", 7), (7.0, 7), (None, None), ("", None)]
)
def test_parse_repository_id_accepts_whole_numbers_and_empty(raw: Any, expected: Any) -> None:
    assert parse_repository_id(raw, step_id="s") == expected


# ── git_repository_id per step ─────────────────────────────────────────────────────────────────


def _read_config(raw: Any) -> Any:
    from workflow_steps.read_config.executor import _parse_read_config

    return _parse_read_config({"source": "git", "git_repository_id": raw, "path_template": "p"})


def _read_from_file(raw: Any) -> Any:
    from workflow_steps.read_from_file.executor import _parse_config

    return _parse_config(
        {"source": "git", "git_repository_id": raw, "path": "p", "destination_path": "mybag"}
    )


def _backup_aci(raw: Any) -> Any:
    from workflow_steps.backup_aci_config.executor import _repository_id

    return _repository_id({"git_repository_id": raw})


def _store_artifact(raw: Any) -> Any:
    from pathlib import Path

    from workflow_steps.store_artifact import executor as mod

    with patch.object(mod, "_load_git_repository", return_value={"id": 1}):
        return mod._build_sink(
            {"destination": "git", "git_repository_id": raw}, base_dir=Path("/nonexistent")
        )


_STEPS = [
    pytest.param(_read_config, id="read-config"),
    pytest.param(_read_from_file, id="read-from-file"),
    pytest.param(_backup_aci, id="backup-aci-config"),
    pytest.param(_store_artifact, id="store-artifact"),
]


@pytest.mark.parametrize("parse", _STEPS)
def test_a_text_repository_id_is_refused(parse: Any) -> None:
    with pytest.raises(ValueError):
        parse("abc")


@pytest.mark.parametrize("parse", [s for s in _STEPS if s.id != "backup-aci-config"])
@pytest.mark.parametrize("raw", [pytest.param(True, id="True"), pytest.param(7.9, id="7.9")])
@_LAX_ID
def test_a_bool_or_fractional_repository_id_is_refused(parse: Any, raw: Any) -> None:
    with pytest.raises(ValueError):
        parse(raw)


@_LAX_ID
def test_backup_aci_config_refuses_a_fractional_repository_id() -> None:
    with pytest.raises(ValueError):
        _backup_aci(7.9)


def test_backup_aci_config_already_refuses_true_and_zero() -> None:
    for raw in (True, 0, "0", None, ""):
        with pytest.raises(ValueError):
            _backup_aci(raw)


@pytest.mark.parametrize("parse", [_read_config, _read_from_file])
def test_a_whole_repository_id_is_kept(parse: Any) -> None:
    assert parse("7").git_repository_id == 7
    assert parse(7).git_repository_id == 7


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw", ["abc", pytest.param(True, marks=_LAX_ID), pytest.param(7.9, marks=_LAX_ID)]
)
async def test_open_change_request_never_loads_a_repository_for_a_mangled_id(raw: Any) -> None:
    from workflow_steps.open_change_request import executor as mod

    with patch.object(mod, "load_git_repository", side_effect=ValueError("stop")) as loader:
        outcomes = await call_step(
            mod.execute,
            {"git_repository_id": raw},
            make_context([make_device("d1")]),
            run=make_run(),
        )

    loader.assert_not_called()
    assert "failure" in [o.name for o in outcomes]


# ── boolean flags ──────────────────────────────────────────────────────────────────────────────


@strict_xfail("W11-07", "a typo is read as False: git-push silently commits nothing")
@pytest.mark.parametrize("value", ["ture", "nope", "2"])
def test_commit_before_push_with_a_typo_is_refused(value: str) -> None:
    from workflow_steps.common.git_push_helpers import parse_commit_before_push

    with pytest.raises(ValueError):
        _typo_guard(parse_commit_before_push, {"commit_before_push": value})


@strict_xfail("W11-07", "a typo is read as True")
@pytest.mark.parametrize("value", ["nope", "fasle"])
def test_include_command_header_with_a_typo_is_refused(value: str) -> None:
    from workflow_steps.merge_content.executor import _parse_include_command_header

    with pytest.raises(ValueError):
        _typo_guard(_parse_include_command_header, {"include_command_header": value})


@strict_xfail("W11-07", "bool('false') is True")
def test_update_primary_ipv4_text_false_is_not_true() -> None:
    from workflow_steps.config_to_attributes.executor import _parse_update_primary_ipv4

    assert _parse_update_primary_ipv4({"update_primary_ipv4": "false"}) is False


def _typo_guard(parse: Any, config: dict[str, Any]) -> Any:
    """Return the parsed value; a flag typo must raise before it is silently read as a bool."""
    return parse(config)


@pytest.mark.parametrize(
    ("parse_path", "key", "true_text", "false_text"),
    [
        (
            "workflow_steps.common.git_push_helpers.parse_commit_before_push",
            "commit_before_push",
            "yes",
            "off",
        ),
        (
            "workflow_steps.merge_content.executor._parse_include_command_header",
            "include_command_header",
            "on",
            "no",
        ),
    ],
)
def test_common_bool_spellings_keep_working(
    parse_path: str, key: str, true_text: str, false_text: str
) -> None:
    import importlib

    module_name, _, attr = parse_path.rpartition(".")
    parse = getattr(importlib.import_module(module_name), attr)

    assert parse({key: true_text}) is True
    assert parse({key: false_text}) is False
    assert parse({key: True}) is True
    assert parse({}) is True
