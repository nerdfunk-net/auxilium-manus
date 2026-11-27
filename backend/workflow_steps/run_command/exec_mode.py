"""Exec-mode (show-command) execution for the run-command step."""

from __future__ import annotations

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
from workflow_steps.common.device_runner import Fail, run_per_device
from workflow_steps.common.device_type import connection_device_type
from workflow_steps.common.failure_records import INVALID_INPUT
from workflow_steps.common.step_flags import record_dry_run
from workflow_steps.run_command.constants import STEP_ID
from workflow_steps.run_command.parsing import ParsedRunCommandConfig

logger = logging.getLogger(__name__)

# Per successful device: command -> raw output (``None`` marks a TextFSM raw-text fallback).
_RawOutputs = dict[str, dict[str, str | None]]


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


async def _run_on_device(
    device_id: str, device: DeviceContext, job: _ExecJob, raw_outputs: _RawOutputs
) -> DeviceContext | Fail:
    """One device. A device that succeeds records its raw outputs in ``raw_outputs``; an
    unexpected exception is the runner's (class name and ``FailureInfo``, W3a-05)."""
    host = bare_hostname(device.primary_ip4, device.hostname)
    if not host:
        return Fail(
            "missing_host", f"Device {device_id} has no hostname or primary IP", INVALID_INPUT
        )
    if job.parsed.dry_run:
        raw_outputs[device_id] = {}
        return _dry_run(device, host, job)
    result = await _send(device, host, job)
    rows, outputs = await _store_rows(device_id, result, job)
    command_results = {**device.command_results, job.node_id: rows}
    if not result.success:
        # `result.error` is driver text (it can name a refused line or echo a secret): the cause
        # is the FailureInfo, never that text.
        recorded = device.model_copy(update={"command_results": command_results})
        return Fail("command_failed", "Command execution failed", result.failure, device=recorded)
    raw_outputs[device_id] = outputs
    return device.model_copy(update={"status": DeviceStatus.OK, "command_results": command_results})


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
) -> tuple[dict[str, DeviceContext], dict[str, DeviceContext], _RawOutputs]:
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
    raw_outputs: _RawOutputs = {}

    async def _work(device_id: str, device: DeviceContext) -> DeviceContext | Fail:
        return await _run_on_device(device_id, device, job, raw_outputs)

    batch = await run_per_device(
        context, _work, node_id=node_id, step_id=STEP_ID, log_label=STEP_ID
    )
    return dict(batch.ok), dict(batch.failed), {d: raw_outputs[d] for d in batch.ok}
