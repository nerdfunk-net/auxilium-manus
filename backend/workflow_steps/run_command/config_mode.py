"""Config-mode execution for the run-command step."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from models.failure import failure_from_exception
from models.workflow_context import (
    CommandResult,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
    bare_hostname,
)
from services.artifacts import ArtifactService
from services.network.netmiko.platform import resolve_connection_device_type
from services.network.netmiko.service import NetmikoService
from workflow_steps.common.step_flags import record_dry_run
from workflow_steps.run_command.outcomes import fail_device
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
) -> Any:
    device_type = resolve_connection_device_type(
        network_driver=device.network_driver,
        platform=device.platform,
        override=parsed.network_driver_override,
    )
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


async def _store_run_command_config_mode_results(
    *,
    result: Any,
    commands: list[str],
    device_id: str,
    node_id: str,
    context_run_id: str,
    parsed: ParsedRunCommandConfig,
    artifact_service: ArtifactService,
) -> list[CommandResult]:
    step_results: list[CommandResult] = []
    output_ref = await artifact_service.store(
        content=result.config_output,
        kind="command_output",
        device_id=device_id,
        run_id=context_run_id,
    )
    summary = f"{len(commands)} command(s) sent (config_mode)"
    if result.confirmed_prompts:
        summary += f" · {len(result.confirmed_prompts)} confirmation prompt(s) auto-confirmed"
    step_results.append(
        CommandResult(
            node_id=node_id,
            command="run-command-config-mode",
            success=result.success,
            output_ref=output_ref,
            summary=summary,
        )
    )
    if result.session_log:
        session_log_ref = await artifact_service.store(
            content=result.session_log,
            kind="netmiko_session_log",
            device_id=device_id,
            run_id=context_run_id,
        )
        step_results.append(
            CommandResult(
                node_id=node_id,
                command="netmiko-session-log",
                success=False,
                output_ref=session_log_ref,
                summary=(
                    "Raw Netmiko session log captured up to the failure — inspect "
                    "for confirmation prompts or unexpected CLI output that stalled "
                    "pattern detection"
                ),
            )
        )
    if result.save_output is not None:
        save_ref = await artifact_service.store(
            content=result.save_output,
            kind="command_output",
            device_id=device_id,
            run_id=context_run_id,
        )
        step_results.append(
            CommandResult(
                node_id=node_id,
                command="copy running-config startup-config",
                success=True,
                output_ref=save_ref,
                summary="running-config saved to startup-config",
            )
        )
    return step_results


def _apply_run_command_config_mode_result(
    *,
    device: DeviceContext,
    device_id: str,
    node_id: str,
    result: Any,
    step_results: list[CommandResult],
) -> tuple[str, DeviceContext, bool]:
    updated_command_results = dict(device.command_results)
    updated_command_results[node_id] = step_results
    if not result.success:
        return fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="command_failed",
            message=result.error or "run-command (config_mode) failed",
            command_results=updated_command_results,
            failure=getattr(result, "failure", None),
        )
    enriched = device.model_copy(
        update={
            "status": DeviceStatus.OK,
            "command_results": updated_command_results,
        }
    )
    return device_id, enriched, True


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
) -> tuple[str, DeviceContext, bool]:
    host = bare_hostname(device.primary_ip4, device.hostname)
    if not host:
        return fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="missing_host",
            message=f"Device {device_id} has no hostname or primary IP",
        )

    if parsed.dry_run:
        updated = record_dry_run(
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
        return device_id, updated, True

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
        step_results = await _store_run_command_config_mode_results(
            result=result,
            commands=parsed.commands,
            device_id=device_id,
            node_id=node_id,
            context_run_id=context_run_id,
            parsed=parsed,
            artifact_service=artifact_service,
        )
        return _apply_run_command_config_mode_result(
            device=device,
            device_id=device_id,
            node_id=node_id,
            result=result,
            step_results=step_results,
        )
    except Exception as exc:
        return fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code=type(exc).__name__.lower(),
            message=str(exc),
            failure=failure_from_exception(exc),
        )


async def _run_config_mode_on_device_logged(
    *,
    index: int,
    device_id: str,
    device: DeviceContext,
    total: int,
    run_id: Any,
    node_id: str,
    context_run_id: str,
    parsed: ParsedRunCommandConfig,
    username: str,
    password: str,
    netmiko: NetmikoService,
    artifact_service: ArtifactService,
) -> tuple[str, DeviceContext, bool]:
    host = bare_hostname(device.primary_ip4, device.hostname) or "(no host)"
    logger.info(
        "run-command (config_mode) device %d/%d id=%s host=%s: connecting run_id=%s",
        index,
        total,
        device_id,
        host,
        run_id,
    )
    result = await _run_config_mode_on_device(
        device_id=device_id,
        device=device,
        node_id=node_id,
        run_id=run_id,
        context_run_id=context_run_id,
        parsed=parsed,
        username=username,
        password=password,
        netmiko=netmiko,
        artifact_service=artifact_service,
    )
    _, _, ok = result
    logger.info(
        "run-command (config_mode) device %d/%d id=%s host=%s: %s run_id=%s",
        index,
        total,
        device_id,
        host,
        "ok" if ok else "failed",
        run_id,
    )
    return result


def _partition_config_mode_device_results(
    results: list[tuple[str, DeviceContext, bool]],
) -> tuple[dict[str, DeviceContext], dict[str, DeviceContext]]:
    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}
    for device_id, updated_device, ok in results:
        if ok:
            success_devices[device_id] = updated_device
        else:
            failed_devices[device_id] = updated_device
    return success_devices, failed_devices


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
    total = len(context.devices)
    results = await asyncio.gather(
        *[
            _run_config_mode_on_device_logged(
                index=index,
                device_id=device_id,
                device=device,
                total=total,
                run_id=run_id,
                node_id=node_id,
                context_run_id=context.run_id,
                parsed=parsed,
                username=username,
                password=password,
                netmiko=netmiko,
                artifact_service=artifact_service,
            )
            for index, (device_id, device) in enumerate(context.devices.items(), start=1)
        ]
    )
    return _partition_config_mode_device_results(results)
