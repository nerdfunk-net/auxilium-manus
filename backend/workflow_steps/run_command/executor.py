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
from services.network.netmiko.session_pool import DeviceSessionPool
from workflow_steps.common.credential_resolver import resolve_ssh_credential

logger = logging.getLogger(__name__)

_STEP_ID = "run-command"


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


def _fail_device(
    *,
    device: DeviceContext,
    device_id: str,
    node_id: str,
    code: str,
    message: str,
    command_results: dict[str, list[CommandResult]] | None = None,
) -> tuple[str, DeviceContext, bool]:
    err = DeviceError(
        node_id=node_id,
        step_id=_STEP_ID,
        code=code,
        message=message,
    )
    update: dict[str, Any] = {
        "status": DeviceStatus.FAILED,
        "errors": [*device.errors, err],
    }
    if command_results is not None:
        update["command_results"] = command_results
    failed = device.model_copy(update=update)
    return device_id, failed, False


async def _run_on_device(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    context_run_id: str | None,
    commands: list[str],
    use_textfsm: bool,
    network_driver_override: str | None,
    username: str,
    password: str,
    credential_reference: str,
    netmiko: NetmikoService,
    artifact_service: ArtifactService,
) -> tuple[str, DeviceContext, bool]:
    host = bare_hostname(device.primary_ip4, device.hostname)
    if not host:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="missing_host",
            message=f"Device {device_id} has no hostname or primary IP",
        )

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
            credential_reference=credential_reference,
        )

        step_results: list[CommandResult] = []
        media_type = "application/json" if use_textfsm else "text/plain"
        for command in commands:
            output = result.command_outputs.get(command, "")
            output_ref = await artifact_service.store(
                content=output,
                kind="command_output",
                device_id=device_id,
                run_id=context_run_id,
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
            return _fail_device(
                device=device,
                device_id=device_id,
                node_id=node_id,
                code="command_failed",
                message=result.error or "Command execution failed",
                command_results=updated_command_results,
            )

        enriched = device.model_copy(
            update={
                "status": DeviceStatus.OK,
                "command_results": updated_command_results,
            }
        )
        return device_id, enriched, True
    except Exception as exc:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code=type(exc).__name__.lower(),
            message=str(exc),
        )


async def _run_on_device_logged(
    *,
    index: int,
    device_id: str,
    device: DeviceContext,
    total: int,
    run_id: Any,
    node_id: str,
    context_run_id: str | None,
    commands: list[str],
    use_textfsm: bool,
    network_driver_override: str | None,
    username: str,
    password: str,
    credential_reference: str,
    netmiko: NetmikoService,
    artifact_service: ArtifactService,
) -> tuple[str, DeviceContext, bool]:
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
        context_run_id=context_run_id,
        commands=commands,
        use_textfsm=use_textfsm,
        network_driver_override=network_driver_override,
        username=username,
        password=password,
        credential_reference=credential_reference,
        netmiko=netmiko,
        artifact_service=artifact_service,
    )
    _, _, ok = result
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


def _build_outcomes(
    *,
    context: WorkflowContext,
    success_devices: dict[str, DeviceContext],
    failed_devices: dict[str, DeviceContext],
    command_count: int,
) -> list[StepOutcome]:
    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": success_devices}),
            summary=f"ran {command_count} command(s) on {len(success_devices)} device(s)",
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


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
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

    username, password = resolve_ssh_credential(
        db, credential_reference, acting_user_id=run.triggered_by_id
    )
    netmiko = NetmikoService(pool=device_sessions)
    total = len(context.devices)

    logger.info(
        "run-command run_id=%s devices=%d credential=%s commands=%d textfsm=%s override=%s",
        run.id,
        total,
        credential_reference,
        len(commands),
        use_textfsm,
        network_driver_override,
    )

    results = await asyncio.gather(
        *[
            _run_on_device_logged(
                index=index,
                device_id=device_id,
                device=device,
                total=total,
                run_id=run.id,
                node_id=node_id,
                context_run_id=context.run_id,
                commands=commands,
                use_textfsm=use_textfsm,
                network_driver_override=network_driver_override,
                username=username,
                password=password,
                credential_reference=credential_reference,
                netmiko=netmiko,
                artifact_service=artifact_service,
            )
            for index, (device_id, device) in enumerate(context.devices.items(), start=1)
        ]
    )

    success_devices, failed_devices = _partition_device_results(results)

    logger.info(
        "run-command returning %d/%d devices run_id=%s",
        len(success_devices),
        total,
        run.id,
    )

    return _build_outcomes(
        context=context,
        success_devices=success_devices,
        failed_devices=failed_devices,
        command_count=len(commands),
    )
