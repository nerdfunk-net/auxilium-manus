"""One-token rule for file-system and file names pasted into CLI lines (W3a-13)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from models.workflow_context import DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from workflow_steps.common.device_file_upload import parse_device_token
from workflow_steps.configure_replace_config.executor import execute as configure_replace
from workflow_steps.merge_config.executor import execute as merge_config
from workflow_steps.upload_config.executor import execute as upload_config


def test_a_single_token_is_returned_unchanged() -> None:
    assert parse_device_token("flash:", name="file_system", step_id="s") == "flash:"


@pytest.mark.parametrize("value", ["a b", "a\tb", "a\nb", "a\rb"])
def test_whitespace_inside_the_value_is_refused_naming_step_and_field(value: str) -> None:
    with pytest.raises(ValueError, match="s: file_system must not contain spaces or line breaks"):
        parse_device_token(value, name="file_system", step_id="s")


def _context() -> WorkflowContext:
    device = DeviceContext(
        id="d1", name="r1", hostname="r1", primary_ip4="10.0.0.1/24",
        network_driver="cisco_ios", status=DeviceStatus.OK,
    )  # fmt: skip
    return WorkflowContext(run_id="r", workflow_id="w", devices={"d1": device})


async def _call(execute: Any, config: dict[str, Any]) -> None:
    with patch("workflow_steps.common.run_session.object_session", return_value=MagicMock()):
        await execute(
            config={"credential_reference": "c", **config},
            context=_context(),
            run=MagicMock(run_inputs={}),
            artifact_service=InMemoryArtifactService(),
            node_id="n",
            device_sessions=MagicMock(),
        )


@pytest.mark.asyncio
async def test_upload_config_refuses_a_name_with_a_space() -> None:
    config = {
        "content_source": "running_config",
        "destination_filename": "a b.cfg",
        "file_system": "flash:",
    }
    with pytest.raises(ValueError, match="upload-config: destination_filename must not contain"):
        await _call(upload_config, config)
    with pytest.raises(ValueError, match="upload-config: file_system must not contain"):
        await _call(
            upload_config, {**config, "destination_filename": "a.cfg", "file_system": "f s:"}
        )


@pytest.mark.asyncio
async def test_merge_config_refuses_a_source_filename_with_a_line_break() -> None:
    with pytest.raises(ValueError, match="merge-config: source_filename must not contain"):
        await _call(merge_config, {"source_filename": "flash:a.cfg\nreload"})


@pytest.mark.asyncio
async def test_configure_replace_refuses_a_name_with_a_space() -> None:
    config = {"destination_filename": "a b.cfg", "file_system": "flash:"}
    with pytest.raises(ValueError, match="configure-replace-config: destination_filename must"):
        await _call(configure_replace, config)
    with pytest.raises(ValueError, match="configure-replace-config: file_system must"):
        await _call(configure_replace, {"destination_filename": "a.cfg", "file_system": "f s:"})
