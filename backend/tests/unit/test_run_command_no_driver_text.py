"""W3a-10 / S4: run-command stores a class name and a FailureInfo, never driver or device text."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.failure import FailureInfo
from models.workflow_context import DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.network.netmiko.connection import CommandResult, DeployResult
from workflow_steps.run_command.executor import execute

_LEAK = "password=hunter2 refused line 'enable secret 5 $1$abc'"
_REJECTED = FailureInfo(phase="command", kind="command_error", hint="check_command_syntax")


async def _run(mode: str, *, result=None, raised: Exception | None = None):
    device = DeviceContext(
        id="d1",
        name="r1",
        hostname="r1",
        primary_ip4="10.0.0.1/24",
        network_driver="cisco_ios",
        status=DeviceStatus.OK,
    )
    with (
        patch("workflow_steps.common.run_session.object_session", return_value=MagicMock()),
        patch(
            "workflow_steps.run_command.executor.resolve_ssh_credential",
            return_value=("admin", "secret"),
        ),
        patch("workflow_steps.run_command.executor.NetmikoService") as netmiko_cls,
    ):
        method = "send_commands" if mode == "exec_mode" else "deploy_config"
        mock = AsyncMock(side_effect=raised) if raised else AsyncMock(return_value=result)
        setattr(netmiko_cls.return_value, method, mock)
        outcomes = await execute(
            config={
                "credential_reference": "lab",
                "commands": ["show version"],
                "execution_mode": mode,
                "parser": "none",
            },
            context=WorkflowContext(run_id="u", workflow_id="w", devices={"d1": device}),
            run=MagicMock(id=1),
            artifact_service=InMemoryArtifactService(),
            node_id="n1",
            device_sessions=MagicMock(),
        )
    failed = next(o for o in outcomes if o.name == "failure")
    return failed.context.devices["d1"].errors[-1]


@pytest.mark.asyncio
async def test_exec_mode_failed_result_text_is_not_stored() -> None:
    result = CommandResult(success=False, output="", error=_LEAK, failure=_REJECTED)
    error = await _run("exec_mode", result=result)
    assert (error.code, error.message, error.failure) == (
        "command_failed",
        "Command execution failed",
        _REJECTED,
    )


@pytest.mark.asyncio
async def test_config_mode_failed_result_text_is_not_stored() -> None:
    result = DeployResult(success=False, config_output="", error=_LEAK, failure=_REJECTED)
    error = await _run("config_mode", result=result)
    assert (error.code, error.message, error.failure) == (
        "command_failed",
        "run-command (config_mode) failed",
        _REJECTED,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["exec_mode", "config_mode"])
async def test_exception_text_is_reduced_to_the_class_name(mode: str) -> None:
    error = await _run(mode, raised=ConnectionError(_LEAK))
    assert (error.code, error.message) == ("connectionerror", "ConnectionError")
    assert error.failure is not None and error.failure.exception_type == "ConnectionError"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["exec_mode", "config_mode"])
async def test_a_value_error_keeps_the_step_written_text(mode: str) -> None:
    error = await _run(mode, raised=ValueError("no commands to run"))
    assert (error.code, error.message) == ("valueerror", "no commands to run")
