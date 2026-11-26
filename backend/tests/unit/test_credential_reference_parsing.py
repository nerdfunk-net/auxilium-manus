"""W3a-12: five SSH steps parse their credential reference with the rest of the config.

``run-command`` (Run Command), ``deploy-rendered-template`` (Deploy rendered Template),
``merge-config`` (Merge Config), ``upload-config`` (Upload Config) and ``upload-binary`` (Upload
Binary) used to build a parsed config whose ``credential_reference`` was a placeholder and patch it
in ``execute`` with ``dataclasses.replace``. The parser now takes the run inputs and returns a
complete object; the guard keeps the two-phase pattern from coming back.
"""

from __future__ import annotations

import ast
import importlib
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from models.workflow_context import DeviceContext, WorkflowContext
from services.artifacts import InMemoryArtifactService
from tests.unit._step_helpers import patch_object_session
from workflow_steps.deploy_rendered_template.executor import _parse_deploy_config
from workflow_steps.merge_config.executor import _parse_merge_config
from workflow_steps.run_command.parsing import parse_run_command_config
from workflow_steps.upload_binary.executor import _parse_upload_binary
from workflow_steps.upload_config.executor import _parse_upload_config

_STEPS = Path(__file__).resolve().parents[2] / "workflow_steps"

_BASE: dict[str, dict[str, Any]] = {
    "run-command": {"commands": ["show version"]},
    "deploy-rendered-template": {"source_step_node_id": "render-1"},
    "merge-config": {"source_filename": "r1.cfg"},
    "upload-config": {
        "source_step_node_id": "render-1",
        "destination_filename": "r1.cfg",
        "file_system": "flash:",
    },
    "upload-binary": {
        "git_repository_id": 3,
        "source_path": "images/ios.bin",
        "file_system": "flash:",
    },
}
_PARSERS: dict[str, Callable[..., Any]] = {
    "run-command": parse_run_command_config,
    "deploy-rendered-template": _parse_deploy_config,
    "merge-config": _parse_merge_config,
    "upload-config": _parse_upload_config,
    "upload-binary": _parse_upload_binary,
}


@pytest.mark.parametrize("step", sorted(_PARSERS))
def test_a_literal_reference_is_parsed(step: str) -> None:
    parsed = _PARSERS[step]({**_BASE[step], "credential_reference": " lab-ssh "}, None)
    assert parsed.credential_reference == "lab-ssh"


@pytest.mark.parametrize("step", sorted(_PARSERS))
def test_a_run_parameter_reference_is_read_from_the_run_inputs(step: str) -> None:
    config = {**_BASE[step], "credential_source": "run_param", "credential_param": "cred"}
    parsed = _PARSERS[step](config, {"cred": "site-a-ssh"})
    assert parsed.credential_reference == "site-a-ssh"


@pytest.mark.parametrize("step", sorted(_PARSERS))
def test_a_missing_run_parameter_is_a_configuration_error(step: str) -> None:
    config = {**_BASE[step], "credential_source": "run_param", "credential_param": "cred"}
    with pytest.raises(ValueError, match="'cred' is not present"):
        _PARSERS[step](config, {})


def _replaces_a_credential(path: Path) -> list[int]:
    lines = []
    for node in ast.walk(ast.parse(path.read_text())):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "replace"
            and any(k.arg == "credential_reference" for k in node.keywords)
        ):
            lines.append(node.lineno)
    return lines


def test_no_step_patches_a_credential_into_a_parsed_config() -> None:
    offenders = {
        str(path.relative_to(_STEPS)): lines
        for path in sorted(_STEPS.rglob("*.py"))
        if (lines := _replaces_a_credential(path))
    }
    assert offenders == {}, "parse the credential reference with the config (W3a-12)"


class _Stop(Exception):
    """Raised by the credential lookup: the test only needs the reference that reached it."""


_EXECUTORS = {
    "run-command": "workflow_steps.run_command.executor",
    "deploy-rendered-template": "workflow_steps.deploy_rendered_template.executor",
    "merge-config": "workflow_steps.merge_config.executor",
    "upload-config": "workflow_steps.upload_config.executor",
    "upload-binary": "workflow_steps.upload_binary.executor",
}


@pytest.mark.asyncio
@pytest.mark.parametrize("step", sorted(_EXECUTORS))
async def test_execute_hands_the_run_inputs_to_the_parser(step: str) -> None:
    module = importlib.import_module(_EXECUTORS[step])
    run = MagicMock(id=1, triggered_by_id=5, run_inputs={"cred": "site-a-ssh"})
    device = DeviceContext(id="d1", name="r1", hostname="r1", primary_ip4="10.0.0.1/24")
    config = {**_BASE[step], "credential_source": "run_param", "credential_param": "cred"}
    with (
        patch_object_session(),
        patch(f"{_EXECUTORS[step]}.resolve_ssh_credential", side_effect=_Stop) as lookup,
        pytest.raises(_Stop),
    ):
        await module.execute(
            config=config,
            context=WorkflowContext(run_id="r", workflow_id="w", devices={"d1": device}),
            run=run,
            artifact_service=InMemoryArtifactService(),
            node_id="n1",
            device_sessions=MagicMock(),
        )
    assert lookup.call_args.args[1] == "site-a-ssh"
