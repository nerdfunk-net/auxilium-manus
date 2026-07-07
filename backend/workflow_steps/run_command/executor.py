"""Executor for the run-command step."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from sqlalchemy.orm import object_session

from core.models.runs import WorkflowRun
from models.workflow_context import (
    CommandResult,
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
    bare_hostname,
)
from services.artifacts import ArtifactService
from services.network.netmiko.platform import resolve_connection_device_type
from services.network.netmiko.service import NetmikoService
from workflow_steps.common.credential_resolver import resolve_ssh_credential

logger = logging.getLogger(__name__)


def _default_config() -> dict[str, Any]:
    from workflow_steps.run_command.config import get_config

    return get_config()


def _parse_commands(config: dict[str, Any]) -> list[str]:
    raw = config.get("commands")
    if raw is None:
        raw = _default_config().get("commands", [])
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            raw = []
        else:
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError:
                raw = [line.strip() for line in stripped.splitlines() if line.strip()]
    if not isinstance(raw, list):
        raise ValueError("run-command: commands must be a list of strings")
    commands = [str(command).strip() for command in raw if str(command).strip()]
    if not commands:
        raise ValueError("run-command: at least one command is required")
    return commands


def _parse_use_textfsm(config: dict[str, Any]) -> bool:
    value = config.get("use_textfsm", False)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _build_summary(*, content: str, use_textfsm: bool) -> str:
    if use_textfsm:
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                return f"{len(parsed)} row(s) parsed"
        except json.JSONDecodeError:
            pass
    return f"{len(content.encode('utf-8'))} bytes"


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
) -> list[StepOutcome]:
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    credential_reference = str(config.get("credential_reference") or "").strip()
    commands = _parse_commands(config)
    use_textfsm = _parse_use_textfsm(config)
    network_driver_override = str(config.get("network_driver_override") or "").strip() or None

    db = object_session(run)
    if db is None:
        raise RuntimeError("run-command: WorkflowRun has no active DB session")

    username, password = resolve_ssh_credential(db, credential_reference)
    netmiko = NetmikoService()

    logger.info(
        "run-command run_id=%s devices=%d credential=%s commands=%d textfsm=%s override=%s",
        run.id,
        len(context.devices),
        credential_reference,
        len(commands),
        use_textfsm,
        network_driver_override,
    )

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}

    async def run_on_device(
        device_id: str,
        device: DeviceContext,
    ) -> tuple[str, DeviceContext, bool]:
        host = bare_hostname(device.primary_ip4, device.hostname)
        if not host:
            err = DeviceError(
                node_id=node_id,
                step_id="run-command",
                code="missing_host",
                message=f"Device {device_id} has no hostname or primary IP",
            )
            failed = device.model_copy(
                update={
                    "status": DeviceStatus.FAILED,
                    "errors": [*device.errors, err],
                }
            )
            return device_id, failed, False

        device_type = resolve_connection_device_type(
            network_driver=device.network_driver,
            platform=device.platform,
            override=network_driver_override,
        )

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
            )

            step_results: list[CommandResult] = []
            media_type = "application/json" if use_textfsm else "text/plain"
            for command in commands:
                output = result.command_outputs.get(command, "")
                output_ref = await artifact_service.store(
                    content=output,
                    kind="command_output",
                    device_id=device_id,
                    run_id=context.run_id,
                    media_type=media_type,
                )
                step_results.append(
                    CommandResult(
                        node_id=node_id,
                        command=command,
                        success=result.success,
                        output_ref=output_ref,
                        summary=_build_summary(content=output, use_textfsm=use_textfsm),
                    )
                )

            updated_command_results = dict(device.command_results)
            updated_command_results[node_id] = step_results

            if not result.success:
                err = DeviceError(
                    node_id=node_id,
                    step_id="run-command",
                    code="command_failed",
                    message=result.error or "Command execution failed",
                )
                failed = device.model_copy(
                    update={
                        "status": DeviceStatus.FAILED,
                        "errors": [*device.errors, err],
                        "command_results": updated_command_results,
                    }
                )
                return device_id, failed, False

            enriched = device.model_copy(
                update={
                    "status": DeviceStatus.OK,
                    "command_results": updated_command_results,
                }
            )
            return device_id, enriched, True
        except Exception as exc:
            err = DeviceError(
                node_id=node_id,
                step_id="run-command",
                code=type(exc).__name__.lower(),
                message=str(exc),
            )
            failed = device.model_copy(
                update={
                    "status": DeviceStatus.FAILED,
                    "errors": [*device.errors, err],
                }
            )
            return device_id, failed, False

    results = await asyncio.gather(
        *[run_on_device(device_id, device) for device_id, device in context.devices.items()]
    )

    for device_id, updated_device, ok in results:
        if ok:
            success_devices[device_id] = updated_device
        else:
            failed_devices[device_id] = updated_device

    logger.info(
        "run-command returning %d/%d devices run_id=%s",
        len(success_devices),
        len(context.devices),
        run.id,
    )

    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": success_devices}),
            summary=f"ran {len(commands)} command(s) on {len(success_devices)} device(s)",
        )
    ]
    if failed_devices:
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(update={"devices": failed_devices}),
                summary=f"{len(failed_devices)} device(s) failed",
            )
        )
    return outcomes
