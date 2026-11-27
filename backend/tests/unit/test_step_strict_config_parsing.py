"""Strict parsing of step flags and repository ids (P-T "write first" for P-A, W11-07).

Tests marked ``strict_xfail`` document today's lax parsing: they fail on the current code and
pass once P-A moves the site to ``step_flags`` / ``parse_repository_id``. Plain tests pin the
behaviour that must not change.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tests.unit._step_helpers import call_step, make_context, make_device, make_run
from workflow_steps.common.git_repository_loader import parse_repository_id

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

    with patch.object(mod, "load_git_repository", return_value={"id": 1}):
        return mod._build_sink(
            {"destination": "git", "git_repository_id": raw}, base_dir=Path("/nonexistent")
        ).sink


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
def test_a_bool_or_fractional_repository_id_is_refused(parse: Any, raw: Any) -> None:
    with pytest.raises(ValueError):
        parse(raw)


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
@pytest.mark.parametrize("raw", ["abc", True, 7.9])
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


def _commit_before_push(value: Any) -> None:
    from workflow_steps.git_push.executor import _push_operation

    service = MagicMock()
    service.get_repo_path.return_value = "/nonexistent"
    _push_operation(
        service, {"id": 1}, {"commit_before_push": value}, make_context([make_device("d1")])
    )


@pytest.mark.parametrize("value", ["ture", "nope", "2"])
def test_commit_before_push_with_a_typo_is_refused(value: str) -> None:
    with pytest.raises(ValueError, match="commit_before_push must be true or false"):
        _commit_before_push(value)


def _include_header(**config: Any) -> bool:
    from workflow_steps.merge_content.executor import _parse_merge_config

    return _parse_merge_config(config).include_command_header


@pytest.mark.parametrize("value", ["nope", "fasle"])
def test_include_command_header_with_a_typo_is_refused(value: str) -> None:
    with pytest.raises(ValueError, match="include_command_header must be true or false"):
        _include_header(include_command_header=value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("on", True), ("no", False), ("false", False), (True, True), (False, False), (1, True)],
)
def test_common_bool_spellings_keep_working(value: Any, expected: bool) -> None:
    assert _include_header(include_command_header=value) is expected
    assert _include_header() is True


def test_store_artifact_git_sink_gets_each_flag_from_its_own_key() -> None:
    from pathlib import Path

    from workflow_steps.store_artifact import executor as mod

    def sink(**flags: bool) -> object:
        with patch.object(mod, "load_git_repository", return_value={"id": 1}):
            return mod._build_sink(
                {"destination": "git", "git_repository_id": 1, **flags}, base_dir=Path("/x")
            ).sink

    attributes = ("_pull_before_write", "_commit_after_write", "_push_after_write")
    default = sink()
    assert [getattr(default, a) for a in attributes] == [False, False, False]
    for key, attribute in (
        ("pull_before_write", "_pull_before_write"),
        ("commit_after_write", "_commit_after_write"),
        ("push_after_write", "_push_after_write"),
    ):
        built = sink(**{key: True})
        on = {a for a in attributes if getattr(built, a)}
        assert on == {attribute}
