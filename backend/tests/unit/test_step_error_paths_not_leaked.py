"""Stored step errors name a path relative to its root, never the server's absolute path (QW9).

``compare-data`` / ``compare-snapshot`` (filesystem reference), ``batfish-validate-facts``
(``facts_source: git``) and ``read-config`` put error text in a persisted ``DeviceError`` or in a
``ValueError`` that every reader of the run sees (W4-18, W7-10, W3b-05).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from _git_helpers import acheckout_of

from tests.unit._step_helpers import call_step, make_context, make_device
from workflow_steps.batfish_validate_facts import executor as validate_facts
from workflow_steps.compare_data import reference_reader
from workflow_steps.read_config.executor import execute as read_config


def test_compare_data_filesystem_reference_not_found_names_the_relative_path(
    tmp_path: Path,
) -> None:
    with patch.object(reference_reader.settings, "data_directory", str(tmp_path)):
        with pytest.raises(FileNotFoundError) as raised:
            reference_reader._read_filesystem_sync({}, "sw1.cfg")

    assert str(raised.value) == "Reference file not found: sw1.cfg"
    assert str(tmp_path) not in str(raised.value)


@pytest.mark.asyncio
async def test_batfish_validate_facts_invalid_yaml_names_the_relative_path(
    tmp_path: Path,
) -> None:
    (tmp_path / "facts").mkdir()
    (tmp_path / "facts" / "a.yaml").write_text("not: [a nodes mapping\n", encoding="utf-8")

    with (
        patch.object(validate_facts, "load_git_repository", return_value={"id": 7}),
        patch.object(validate_facts, "agit_checkout", return_value=acheckout_of(tmp_path)),
        pytest.raises(ValueError) as raised,
    ):
        await validate_facts._build_git_facts_corpus(
            merged_config={"git_repository_id": 7, "base_path": "facts", "glob_pattern": "*.yaml"}
        )

    message = str(raised.value)
    assert "facts/a.yaml" in message
    assert str(tmp_path.resolve()) not in message
    assert str(tmp_path) not in message


@pytest.mark.asyncio
async def test_read_config_permission_error_keeps_only_the_class_name(tmp_path: Path) -> None:
    (tmp_path / "d1.cfg").write_text("hostname d1\n", encoding="utf-8")

    def refuse(self: Path, *args: object, **kwargs: object) -> str:
        raise PermissionError(13, "Permission denied", str(self))

    with (
        patch("workflow_steps.common.file_source_root.get_db_session"),
        patch("workflow_steps.common.file_source_root.GeneralSettingsService") as settings_service,
        patch.object(Path, "read_text", refuse),
    ):
        settings_service.return_value.resolved_export_directory.return_value = tmp_path
        outcomes = await call_step(
            read_config,
            {"source": "filesystem", "path_template": "{device.name}.cfg"},
            make_context([make_device("d1")]),
        )

    error = next(o for o in outcomes if o.name == "failure").context.devices["d1"].errors[-1]
    assert error.code == "permissionerror"
    assert error.message == "PermissionError"
    assert str(tmp_path) not in error.message
