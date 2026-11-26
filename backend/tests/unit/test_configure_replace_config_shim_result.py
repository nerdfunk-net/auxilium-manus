"""W3a-07: ``configure-replace-config`` (Configure Replace Config) passes its job timeout as an
argument and reports "outcome unknown" as a flag, not as a ``ContextVar`` and a marker string."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from models.failure import FailureInfo
from services.pyats.common.exceptions import PyATSAPIError
from workflow_steps.configure_replace_config import shim_jobs
from workflow_steps.configure_replace_config.executor import _replace_failure
from workflow_steps.configure_replace_config.shim_jobs import ShimResult, run_diff, run_shim_job

pytestmark = pytest.mark.asyncio

_DEVICE = {"name": "d1", "host": "10.0.0.1"}
_API_FAILURE = FailureInfo(phase="api", kind="server_error")


def _shim(*, response=None, error: Exception | None = None) -> MagicMock:
    shim = MagicMock()
    shim.run_job = AsyncMock(return_value=response, side_effect=error)
    return shim


async def _job(shim: MagicMock, *, timeout: float = 240.0) -> ShimResult:
    return await run_shim_job(
        shim, MagicMock(), operation="execute", shim_device=_DEVICE, commands=["c"], timeout=timeout
    )


async def test_the_job_timeout_is_an_argument() -> None:
    shim = _shim(response={"results": {"d1": {"success": True, "commands": {"c": {"raw": "x"}}}}})

    result = await _job(shim, timeout=240.0)

    assert shim.run_job.await_args.kwargs["timeout_seconds"] == 240.0
    assert result == ShimResult(ok=True, entries={"c": {"raw": "x"}})


async def test_the_module_has_no_context_variable_any_more() -> None:
    assert not hasattr(shim_jobs, "JOB_TIMEOUT")
    assert not hasattr(shim_jobs, "OUTCOME_UNKNOWN")
    assert not hasattr(shim_jobs, "ShimError")


@pytest.mark.parametrize(
    "error",
    [
        PyATSAPIError("pyATS shim job request timed out after 135.0 seconds"),
        PyATSAPIError("gateway gave up", code="timeout"),
    ],
)
async def test_a_client_timeout_is_flagged_outcome_unknown(error: PyATSAPIError) -> None:
    result = await _job(_shim(error=error))

    assert not result.ok
    assert result.outcome_unknown
    assert result.error == str(error)  # the sentence for the user is added by the replace only


async def test_another_api_error_keeps_its_record_and_is_not_unknown() -> None:
    error = PyATSAPIError("shim refused the job", http_status=502)

    result = await _job(_shim(error=error))

    assert result == ShimResult(ok=False, error="shim refused the job", failure=error.failure)
    assert result.failure is not None


async def test_a_device_failure_in_the_response_keeps_its_record() -> None:
    result = await _job(_shim(response={"results": {"d1": {"success": False, "error": "boom"}}}))

    assert result == ShimResult(
        ok=False,
        error="boom",
        failure=FailureInfo(phase="command", kind="command_error"),
    )


async def test_the_diff_job_gets_the_same_timeout() -> None:
    shim = _shim(
        response={"results": {"d1": {"success": True, "commands": {"diff": {"raw": "d"}}}}}
    )

    ok, text, error = await run_diff(
        shim, MagicMock(), shim_device=_DEVICE, diff_command="diff", timeout=90.0
    )

    assert (ok, text, error) == (True, "d", None)
    assert shim.run_job.await_args.kwargs["timeout_seconds"] == 90.0


async def test_an_unknown_outcome_is_a_task_timeout_with_the_warning() -> None:
    fail = _replace_failure("timed out", outcome_unknown=True)

    assert fail.code == "replace_failed"
    assert fail.failure == FailureInfo(phase="task", kind="task_timeout", hint="retry_later")
    assert "may still have been applied" in fail.message


async def test_a_known_refusal_keeps_its_own_record_and_no_warning() -> None:
    fail = _replace_failure("refused", failure=_API_FAILURE)

    assert fail.failure == _API_FAILURE
    assert "may still have been applied" not in fail.message


async def test_device_text_that_looks_like_the_warning_is_not_a_timeout() -> None:
    # The old code tested the message for the marker sentence; a device that printed it would
    # have turned a refusal into "outcome unknown".
    text = "% -- the job may still have been applied on the device; check it before re-running"

    assert _replace_failure(text).failure is None


async def test_both_diff_checks_send_the_device_job_timeout() -> None:
    from models.workflow_context import DeviceContext, DeviceStatus
    from services.artifacts import InMemoryArtifactService
    from workflow_steps.configure_replace_config.diff_checks import (
        Target,
        pre_replace_diff,
        verify_after_replace,
    )

    response = {"results": {"d1": {"success": True, "commands": {"diff": {"raw": "+ x"}}}}}
    shim = _shim(response=response)
    target = Target(
        bag={},
        source_id="s",
        shim=shim,
        shim_credentials=MagicMock(),
        shim_device=_DEVICE,
        job_timeout=77.0,
    )
    device = DeviceContext(id="d1", name="d1", hostname="d1", status=DeviceStatus.OK)
    common = {
        "device_id": "d1",
        "device": device,
        "node_id": "n",
        "diff_command": "diff",
        "destination_filename": "f",
        "file_system": "flash:",
        "artifact_service": InMemoryArtifactService(),
        "context_run_id": "r",
    }

    await pre_replace_diff(target, timeout_minutes=2, **common)
    await verify_after_replace(target, pre_diff_artifact_ref=None, **common)

    assert [c.kwargs["timeout_seconds"] for c in shim.run_job.await_args_list] == [77.0, 77.0]
