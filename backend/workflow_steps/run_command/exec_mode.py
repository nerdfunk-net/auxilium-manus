"""Exec-mode (show-command) execution for the run-command step."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from models.workflow_context import (
    CommandResult,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
    bare_hostname,
)
from services.artifacts import ArtifactService
from services.network.netmiko.connection import CommandResult as NetmikoCommandResult
from services.network.netmiko.service import NetmikoService
from workflow_steps.common.device_outcomes import fail_device_with_error, mark_device_failed
from workflow_steps.common.device_type import connection_device_type
from workflow_steps.common.failure_records import INVALID_INPUT
from workflow_steps.common.partial_outcomes import device_error_from_exception
from workflow_steps.common.step_flags import record_dry_run
from workflow_steps.run_command.constants import STEP_ID
from workflow_steps.run_command.parsing import ParsedRunCommandConfig

logger = logging.getLogger(__name__)


def _build_summary(*, content: str, structured: bool) -> str:
    if structured:
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                return f"{len(parsed)} row(s) parsed"
        except json.JSONDecodeError:  # noqa: S110  # not JSON: keep the raw text
            pass
    return f"{len(content.encode('utf-8'))} bytes"


@dataclass(frozen=True)
class _ExecJob:
    """What every device of one exec-mode run shares (W3a-17: replaces 18 forwarded kwargs)."""

    node_id: str
    run_id: Any
    context_run_id: str
    parsed: ParsedRunCommandConfig
    username: str
    password: str
    netmiko: NetmikoService
    artifact_service: ArtifactService

    @property
    def use_textfsm(self) -> bool:
        return self.parsed.parser_mode == "textfsm"


_DeviceRun = tuple[str, DeviceContext, bool, dict[str, str | None]]


def _dry_run(device: DeviceContext, host: str, job: _ExecJob) -> DeviceContext:
    return record_dry_run(
        device=device,
        node_id=job.node_id,
        payload={
            "would_execute": True,
            "execution_mode": "exec_mode",
            "commands": job.parsed.commands,
            "host": host,
        },
    )


async def _send(device: DeviceContext, host: str, job: _ExecJob) -> NetmikoCommandResult:
    parsed = job.parsed
    # An unknown platform fails this device (UnsupportedPlatformError carries the failure).
    device_type = connection_device_type(device, parsed.network_driver_override)
    return await job.netmiko.send_commands(
        host=host,
        network_driver=device.network_driver,
        platform=device.platform,
        username=job.username,
        password=job.password,
        commands=parsed.commands,
        use_textfsm=job.use_textfsm,
        device_type=device_type,
        credential_reference=parsed.credential_reference,
        read_timeout=parsed.read_timeout,
        auto_confirm_prompts=parsed.auto_confirm_prompts,
        fail_on_cli_error=parsed.fail_on_cli_error,
        retry=parsed.retry,
    )


async def _store_rows(
    device_id: str, result: NetmikoCommandResult, job: _ExecJob
) -> tuple[list[CommandResult], dict[str, str | None]]:
    """One stored artifact and one result row per command; the raw outputs for the parsers."""
    confirmed = set(result.confirmed_prompts)
    if confirmed:
        logger.warning(
            "run-command auto-confirmed %d prompt(s) run_id=%s node_id=%s device_id=%s commands=%s",
            len(confirmed),
            job.run_id,
            job.node_id,
            device_id,
            sorted(confirmed),
        )
    step_results: list[CommandResult] = []
    raw_outputs: dict[str, str | None] = {}
    for command in job.parsed.commands:
        output = result.command_outputs.get(command, "")
        structured = command in result.structured_commands
        # With TextFSM, None marks a raw-text fallback (no template matched): not a
        # parse result, whatever the text looks like.
        raw_outputs[command] = output if structured or not job.use_textfsm else None
        output_ref = await job.artifact_service.store(
            content=output,
            kind="command_output",
            device_id=device_id,
            run_id=job.context_run_id,
            media_type="application/json" if structured else "text/plain",
        )
        summary = _build_summary(content=output, structured=structured)
        if command in confirmed:
            summary += " · confirmation prompt auto-confirmed"
        step_results.append(
            CommandResult(
                node_id=job.node_id,
                command=command,
                success=result.success,
                output_ref=output_ref,
                summary=summary,
            )
        )
    return step_results, raw_outputs


def _to_device_result(
    device_id: str,
    device: DeviceContext,
    result: NetmikoCommandResult,
    rows: list[CommandResult],
    raw_outputs: dict[str, str | None],
    job: _ExecJob,
) -> _DeviceRun:
    command_results = {**device.command_results, job.node_id: rows}
    if not result.success:
        failed = mark_device_failed(
            device,
            node_id=job.node_id,
            step_id=STEP_ID,
            code="command_failed",
            # `result.error` is driver text (it can name a refused line or echo a secret):
            # the cause is the FailureInfo, never that text.
            message="Command execution failed",
            command_results=command_results,
            failure=result.failure,
        )
        return device_id, failed, False, {}
    enriched = device.model_copy(
        update={"status": DeviceStatus.OK, "command_results": command_results}
    )
    return device_id, enriched, True, raw_outputs


async def _run_on_device(device_id: str, device: DeviceContext, job: _ExecJob) -> _DeviceRun:
    host = bare_hostname(device.primary_ip4, device.hostname)
    if not host:
        failed = mark_device_failed(
            device,
            node_id=job.node_id,
            step_id=STEP_ID,
            code="missing_host",
            failure=INVALID_INPUT,
            message=f"Device {device_id} has no hostname or primary IP",
        )
        return device_id, failed, False, {}
    if job.parsed.dry_run:
        return device_id, _dry_run(device, host, job), True, {}
    try:
        result = await _send(device, host, job)
        rows, raw_outputs = await _store_rows(device_id, result, job)
        return _to_device_result(device_id, device, result, rows, raw_outputs, job)
    except Exception as exc:
        error = device_error_from_exception(exc, node_id=job.node_id, step_id=STEP_ID)
        return device_id, fail_device_with_error(device, error), False, {}


async def _run_on_device_logged(
    index: int, total: int, device_id: str, device: DeviceContext, job: _ExecJob
) -> _DeviceRun:
    host = bare_hostname(device.primary_ip4, device.hostname) or "(no host)"
    logger.info(
        "run-command device %d/%d id=%s host=%s: connecting run_id=%s",
        index,
        total,
        device_id,
        host,
        job.run_id,
    )
    result = await _run_on_device(device_id, device, job)
    logger.info(
        "run-command device %d/%d id=%s host=%s: %s run_id=%s",
        index,
        total,
        device_id,
        host,
        "ok" if result[2] else "failed",
        job.run_id,
    )
    return result


def _partition_device_results(
    results: list[_DeviceRun],
) -> tuple[dict[str, DeviceContext], dict[str, DeviceContext], dict[str, dict[str, str | None]]]:
    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}
    raw_outputs_by_device: dict[str, dict[str, str | None]] = {}
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
) -> tuple[dict[str, DeviceContext], dict[str, DeviceContext], dict[str, dict[str, str | None]]]:
    """Run ``parsed.commands`` on every device; return (success, failed, raw outputs)."""
    job = _ExecJob(
        node_id=node_id,
        run_id=run_id,
        context_run_id=context.run_id,
        parsed=parsed,
        username=username,
        password=password,
        netmiko=netmiko,
        artifact_service=artifact_service,
    )
    total = len(context.devices)
    results = await asyncio.gather(
        *[
            _run_on_device_logged(index, total, device_id, device, job)
            for index, (device_id, device) in enumerate(context.devices.items(), start=1)
        ]
    )
    return _partition_device_results(results)
