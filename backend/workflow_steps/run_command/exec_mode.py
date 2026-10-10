"""Exec-mode (show-command) execution for the run-command step."""

from __future__ import annotations

import asyncio
import json
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
from services.network.netmiko.connection import RetryPolicy
from services.network.netmiko.platform import resolve_connection_device_type
from services.network.netmiko.service import NetmikoService
from workflow_steps.common.step_flags import record_dry_run
from workflow_steps.run_command.outcomes import fail_device
from workflow_steps.run_command.parsing import ParsedRunCommandConfig

logger = logging.getLogger(__name__)


def _build_summary(*, content: str, use_textfsm: bool) -> str:
    if use_textfsm:
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                return f"{len(parsed)} row(s) parsed"
        except json.JSONDecodeError:  # noqa: S110  # not JSON: keep the raw text
            pass
    return f"{len(content.encode('utf-8'))} bytes"


async def _run_on_device(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    run_id: Any,
    context_run_id: str,
    commands: list[str],
    use_textfsm: bool,
    network_driver_override: str | None,
    username: str,
    password: str,
    credential_reference: str,
    read_timeout: int,
    auto_confirm_prompts: bool,
    dry_run: bool,
    retry: RetryPolicy,
    netmiko: NetmikoService,
    artifact_service: ArtifactService,
) -> tuple[str, DeviceContext, bool, dict[str, str]]:
    host = bare_hostname(device.primary_ip4, device.hostname)
    if not host:
        dev_id, failed, ok = fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="missing_host",
            message=f"Device {device_id} has no hostname or primary IP",
        )
        return dev_id, failed, ok, {}

    device_type = resolve_connection_device_type(
        network_driver=device.network_driver,
        platform=device.platform,
        override=network_driver_override,
    )

    if dry_run:
        updated = record_dry_run(
            device=device,
            node_id=node_id,
            payload={
                "would_execute": True,
                "execution_mode": "exec_mode",
                "commands": commands,
                "host": host,
            },
        )
        return device_id, updated, True, {}

    try:
        result = await netmiko.send_commands(
            host=host,
            network_driver=device.network_driver,
            platform=device.platform,
            username=username,
            password=password,
            commands=commands,
            use_textfsm=use_textfsm,
            device_type=device_type,
            credential_reference=credential_reference,
            read_timeout=read_timeout,
            auto_confirm_prompts=auto_confirm_prompts,
            retry=retry,
        )

        confirmed = set(result.confirmed_prompts)
        if confirmed:
            logger.warning(
                "run-command auto-confirmed %d prompt(s) run_id=%s node_id=%s "
                "device_id=%s commands=%s",
                len(confirmed),
                run_id,
                node_id,
                device_id,
                sorted(confirmed),
            )

        step_results: list[CommandResult] = []
        raw_outputs: dict[str, str] = {}
        media_type = "application/json" if use_textfsm else "text/plain"
        for command in commands:
            output = result.command_outputs.get(command, "")
            raw_outputs[command] = output
            output_ref = await artifact_service.store(
                content=output,
                kind="command_output",
                device_id=device_id,
                run_id=context_run_id,
                media_type=media_type,
            )
            summary = _build_summary(content=output, use_textfsm=use_textfsm)
            if command in confirmed:
                summary += " · confirmation prompt auto-confirmed"
            step_results.append(
                CommandResult(
                    node_id=node_id,
                    command=command,
                    success=result.success,
                    output_ref=output_ref,
                    summary=summary,
                )
            )

        updated_command_results = dict(device.command_results)
        updated_command_results[node_id] = step_results

        if not result.success:
            dev_id, failed, ok = fail_device(
                device=device,
                device_id=device_id,
                node_id=node_id,
                code="command_failed",
                message=result.error or "Command execution failed",
                command_results=updated_command_results,
                failure=result.failure,
            )
            return dev_id, failed, ok, {}

        enriched = device.model_copy(
            update={
                "status": DeviceStatus.OK,
                "command_results": updated_command_results,
            }
        )
        return device_id, enriched, True, raw_outputs
    except Exception as exc:
        dev_id, failed, ok = fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code=type(exc).__name__.lower(),
            message=str(exc),
            failure=failure_from_exception(exc),
        )
        return dev_id, failed, ok, {}


async def _run_on_device_logged(
    *,
    index: int,
    device_id: str,
    device: DeviceContext,
    total: int,
    run_id: Any,
    node_id: str,
    context_run_id: str,
    commands: list[str],
    use_textfsm: bool,
    network_driver_override: str | None,
    username: str,
    password: str,
    credential_reference: str,
    read_timeout: int,
    auto_confirm_prompts: bool,
    dry_run: bool,
    retry: RetryPolicy,
    netmiko: NetmikoService,
    artifact_service: ArtifactService,
) -> tuple[str, DeviceContext, bool, dict[str, str]]:
    host = bare_hostname(device.primary_ip4, device.hostname) or "(no host)"
    logger.info(
        "run-command device %d/%d id=%s host=%s: connecting run_id=%s",
        index,
        total,
        device_id,
        host,
        run_id,
    )
    result = await _run_on_device(
        device_id=device_id,
        device=device,
        node_id=node_id,
        run_id=run_id,
        context_run_id=context_run_id,
        commands=commands,
        use_textfsm=use_textfsm,
        network_driver_override=network_driver_override,
        username=username,
        password=password,
        credential_reference=credential_reference,
        read_timeout=read_timeout,
        auto_confirm_prompts=auto_confirm_prompts,
        dry_run=dry_run,
        retry=retry,
        netmiko=netmiko,
        artifact_service=artifact_service,
    )
    _, _, ok, _ = result
    logger.info(
        "run-command device %d/%d id=%s host=%s: %s run_id=%s",
        index,
        total,
        device_id,
        host,
        "ok" if ok else "failed",
        run_id,
    )
    return result


def _partition_device_results(
    results: list[tuple[str, DeviceContext, bool, dict[str, str]]],
) -> tuple[dict[str, DeviceContext], dict[str, DeviceContext], dict[str, dict[str, str]]]:
    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}
    raw_outputs_by_device: dict[str, dict[str, str]] = {}
    for device_id, updated_device, ok, raw_outputs in results:
        if ok:
            success_devices[device_id] = updated_device
            raw_outputs_by_device[device_id] = raw_outputs
        else:
            failed_devices[device_id] = updated_device
    return success_devices, failed_devices, raw_outputs_by_device


async def run_exec_mode(
    *,
    context: WorkflowContext,
    node_id: str,
    run_id: Any,
    parsed: ParsedRunCommandConfig,
    username: str,
    password: str,
    netmiko: NetmikoService,
    artifact_service: ArtifactService,
) -> tuple[dict[str, DeviceContext], dict[str, DeviceContext], dict[str, dict[str, str]]]:
    """Run ``parsed.commands`` on every device; return (success, failed, raw outputs)."""
    total = len(context.devices)
    use_textfsm = parsed.parser_mode == "textfsm"
    results = await asyncio.gather(
        *[
            _run_on_device_logged(
                index=index,
                device_id=device_id,
                device=device,
                total=total,
                run_id=run_id,
                node_id=node_id,
                context_run_id=context.run_id,
                commands=parsed.commands,
                use_textfsm=use_textfsm,
                network_driver_override=parsed.network_driver_override,
                username=username,
                password=password,
                credential_reference=parsed.credential_reference,
                read_timeout=parsed.read_timeout,
                auto_confirm_prompts=parsed.auto_confirm_prompts,
                dry_run=parsed.dry_run,
                retry=parsed.retry,
                netmiko=netmiko,
                artifact_service=artifact_service,
            )
            for index, (device_id, device) in enumerate(context.devices.items(), start=1)
        ]
    )
    return _partition_device_results(results)
