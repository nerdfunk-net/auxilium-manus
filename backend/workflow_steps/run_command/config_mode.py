"""Config-mode execution for the run-command step."""

from __future__ import annotations

import logging
from typing import Any

from models.workflow_context import (
    CommandResult,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
    bare_hostname,
)
from services.artifacts import ArtifactService
from services.network.netmiko.connection import DeployResult
from services.network.netmiko.service import NetmikoService
from workflow_steps.common.config_push import store_push_result
from workflow_steps.common.device_runner import Fail, run_per_device
from workflow_steps.common.device_type import connection_device_type
from workflow_steps.common.failure_records import INVALID_INPUT
from workflow_steps.common.partial_outcomes import device_error_from_exception
from workflow_steps.common.step_flags import record_dry_run
from workflow_steps.run_command.constants import STEP_ID
from workflow_steps.run_command.parsing import ParsedRunCommandConfig

logger = logging.getLogger(__name__)


async def _run_command_config_mode(
    *,
    host: str,
    device: DeviceContext,
    device_id: str,
    run_id: Any,
    node_id: str,
    parsed: ParsedRunCommandConfig,
    username: str,
    password: str,
    netmiko: NetmikoService,
) -> DeployResult:
    device_type = connection_device_type(device, parsed.network_driver_override)
    result = await netmiko.deploy_config(
        host=host,
        network_driver=device.network_driver,
        platform=device.platform,
        username=username,
        password=password,
        commands=parsed.commands,
        mode="config_mode",
        write_config=parsed.write_config_after_execution,
        device_type=device_type,
        read_timeout=parsed.read_timeout,
        auto_confirm_prompts=parsed.auto_confirm_prompts,
        fail_on_cli_error=parsed.fail_on_cli_error,
        credential_reference=parsed.credential_reference,
        retry=parsed.retry,
    )
    if result.confirmed_prompts:
        logger.warning(
            "run-command (config_mode) auto-confirmed %d prompt(s) run_id=%s "
            "node_id=%s device_id=%s commands=%s",
            len(result.confirmed_prompts),
            run_id,
            node_id,
            device_id,
            result.confirmed_prompts,
        )
    return result


def _apply_run_command_config_mode_result(
    *,
    device: DeviceContext,
    node_id: str,
    result: DeployResult,
    step_results: list[CommandResult],
) -> DeviceContext | Fail:
    updated_command_results = dict(device.command_results)
    updated_command_results[node_id] = step_results
    recorded = device.model_copy(update={"command_results": updated_command_results})
    if not result.success:
        return Fail(
            "command_failed",
            # `result.error` is driver text: the cause is the FailureInfo, never that text.
            "run-command (config_mode) failed",
            result.failure,
            device=recorded,
        )
    return recorded.model_copy(update={"status": DeviceStatus.OK})


async def _run_config_mode_on_device(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    run_id: Any,
    context_run_id: str,
    parsed: ParsedRunCommandConfig,
    username: str,
    password: str,
    netmiko: NetmikoService,
    artifact_service: ArtifactService,
) -> DeviceContext | Fail:
    host = bare_hostname(device.primary_ip4, device.hostname)
    if not host:
        return Fail(
            "missing_host",
            f"Device {device_id} has no hostname or primary IP",
            failure=INVALID_INPUT,
        )

    if parsed.dry_run:
        return record_dry_run(
            device=device,
            node_id=node_id,
            payload={
                "would_execute": True,
                "execution_mode": "config_mode",
                "commands": parsed.commands,
                "host": host,
                "write_config_after_execution": parsed.write_config_after_execution,
            },
        )

    try:
        result = await _run_command_config_mode(
            host=host,
            device=device,
            device_id=device_id,
            run_id=run_id,
            node_id=node_id,
            parsed=parsed,
            username=username,
            password=password,
            netmiko=netmiko,
        )
        step_results = await store_push_result(
            result,
            command_label="run-command-config-mode",
            summary=f"{len(parsed.commands)} command(s) sent (config_mode)",
            device_id=device_id,
            node_id=node_id,
            context_run_id=context_run_id,
            artifact_service=artifact_service,
        )
        return _apply_run_command_config_mode_result(
            device=device, node_id=node_id, result=result, step_results=step_results
        )
    except Exception as exc:
        error = device_error_from_exception(exc, node_id=node_id, step_id="run-command")
        return Fail(error.code, error.message, error.failure)


async def run_config_mode(
    *,
    context: WorkflowContext,
    node_id: str,
    run_id: Any,
    parsed: ParsedRunCommandConfig,
    username: str,
    password: str,
    netmiko: NetmikoService,
    artifact_service: ArtifactService,
) -> tuple[dict[str, DeviceContext], dict[str, DeviceContext]]:
    """Send ``parsed.commands`` in config mode to every device; return (success, failed)."""

    async def _work(device_id: str, device: DeviceContext) -> DeviceContext | Fail:
        return await _run_config_mode_on_device(
            device_id=device_id,
            device=device,
            node_id=node_id,
            run_id=run_id,
            context_run_id=context.run_id,
            parsed=parsed,
            username=username,
            password=password,
            netmiko=netmiko,
            artifact_service=artifact_service,
        )

    batch = await run_per_device(
        context, _work, node_id=node_id, step_id=STEP_ID, log_label="run-command (config_mode)"
    )
    return dict(batch.ok), dict(batch.failed)
