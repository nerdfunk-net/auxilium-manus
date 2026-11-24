"""The result-store block of config-mode run-command and deploy-rendered-template (W3a-06)."""

from __future__ import annotations

import pytest

from services.artifacts import InMemoryArtifactService
from services.network.netmiko.connection import DeployResult
from workflow_steps.common.config_push import store_push_result


async def _store(result: DeployResult, artifacts: InMemoryArtifactService):  # noqa: ANN202
    return await store_push_result(
        result,
        command_label="deploy-rendered-template",
        summary="3 line(s) deployed (config_mode)",
        device_id="d1",
        node_id="n1",
        context_run_id="run-1",
        artifact_service=artifacts,
    )


@pytest.mark.asyncio
async def test_a_plain_success_stores_one_result_with_the_given_label_and_summary() -> None:
    artifacts = InMemoryArtifactService()

    rows = await _store(DeployResult(success=True, config_output="ok"), artifacts)

    assert len(rows) == 1
    row = rows[0]
    assert (row.node_id, row.command, row.success) == ("n1", "deploy-rendered-template", True)
    assert row.summary == "3 line(s) deployed (config_mode)"
    assert row.output_ref is not None
    assert await artifacts.resolve(row.output_ref) == "ok"


@pytest.mark.asyncio
async def test_confirmed_prompts_are_counted_in_the_summary() -> None:
    result = DeployResult(success=True, config_output="", confirmed_prompts=["a", "b"])

    rows = await _store(result, InMemoryArtifactService())

    assert rows[0].summary == (
        "3 line(s) deployed (config_mode) · 2 confirmation prompt(s) auto-confirmed"
    )


@pytest.mark.asyncio
async def test_a_session_log_is_kept_as_a_failed_row_with_its_artifact() -> None:
    artifacts = InMemoryArtifactService()
    result = DeployResult(success=False, config_output="x", session_log="RAW LOG")

    rows = await _store(result, artifacts)

    assert [r.command for r in rows] == ["deploy-rendered-template", "netmiko-session-log"]
    assert rows[0].success is False
    assert rows[1].success is False
    assert rows[1].output_ref is not None
    assert await artifacts.resolve(rows[1].output_ref) == "RAW LOG"


@pytest.mark.asyncio
async def test_a_save_output_adds_the_startup_config_row() -> None:
    artifacts = InMemoryArtifactService()
    result = DeployResult(success=True, config_output="x", save_output="saved")

    rows = await _store(result, artifacts)

    assert [r.command for r in rows] == [
        "deploy-rendered-template",
        "copy running-config startup-config",
    ]
    assert rows[1].success is True
    assert rows[1].summary == "running-config saved to startup-config"
    assert rows[1].output_ref is not None
    assert await artifacts.resolve(rows[1].output_ref) == "saved"


@pytest.mark.asyncio
async def test_an_empty_save_output_still_counts_as_saved() -> None:
    rows = await _store(
        DeployResult(success=True, config_output="x", save_output=""), InMemoryArtifactService()
    )

    assert len(rows) == 2
