"""Executor for the merge-config step.

Applies a *partial* configuration file already staged on a device (e.g. by an
upstream Upload Config step) by issuing Cisco IOS
``copy <source_filename> running-config`` over SSH and answering the
``Destination filename [running-config]? `` prompt with Enter. The file's
commands are layered onto the running config in the device's non-interactive
batch mode.

Unlike configure-replace-config (complete-config replace via the pyATS shim,
with a rollback timer) this is an additive merge over SSH with no rollback:
whatever the file contains is applied on top of the running config. It always
answers the prompt -- there is no opt-in checkbox.

Reuses the Run Command backend end to end: NetmikoService / DeviceSessionPool,
``resolve_config_reference`` + ``resolve_ssh_credential`` for credentials,
``resolve_connection_device_type`` for the Netmiko device type, ArtifactService
for the stored transcript, and the success/failure StepOutcome shape.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
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
from workflow_steps.common.run_param_reference import resolve_config_reference

logger = logging.getLogger(__name__)

_STEP_ID = "merge-config"
_MIN_READ_TIMEOUT = 5
_MAX_READ_TIMEOUT = 600
_ARTIFACT_KIND = "command_output"


def _default_config() -> dict[str, Any]:
    from workflow_steps.merge_config.config import get_config

    return get_config()


def _parse_read_timeout(config: dict[str, Any]) -> int:
    raw = config.get("read_timeout")
    if raw in (None, ""):
        raw = _default_config()["read_timeout"]
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{_STEP_ID}: read_timeout must be an integer") from exc
    if not (_MIN_READ_TIMEOUT <= value <= _MAX_READ_TIMEOUT):
        raise ValueError(
            f"{_STEP_ID}: read_timeout must be between {_MIN_READ_TIMEOUT} "
            f"and {_MAX_READ_TIMEOUT} seconds"
        )
    return value


@dataclass(frozen=True)
class _ParsedMergeConfig:
    credential_reference: str
    source_filename: str
    network_driver_override: str | None
    read_timeout: int


def _parse_merge_config(config: dict[str, Any]) -> _ParsedMergeConfig:
    source_filename = str(config.get("source_filename") or "").strip()
    if not source_filename:
        raise ValueError(f"{_STEP_ID}: source_filename is required")
    return _ParsedMergeConfig(
        credential_reference="",
        source_filename=source_filename,
        network_driver_override=str(config.get("network_driver_override") or "").strip() or None,
        read_timeout=_parse_read_timeout(config),
    )


def _fail_device(
    *,
    device: DeviceContext,
    device_id: str,
    node_id: str,
    code: str,
    message: str,
    command_results: dict[str, list[CommandResult]] | None = None,
) -> tuple[str, DeviceContext, bool]:
    err = DeviceError(node_id=node_id, step_id=_STEP_ID, code=code, message=message)
    update: dict[str, Any] = {"status": DeviceStatus.FAILED, "errors": [*device.errors, err]}
    if command_results is not None:
        update["command_results"] = command_results
    return device_id, device.model_copy(update=update), False


async def _merge_on_device(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    run_id: Any,
    context_run_id: str,
    parsed: _ParsedMergeConfig,
    username: str,
    password: str,
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
        override=parsed.network_driver_override,
    )
    command = f"copy {parsed.source_filename} running-config"

    try:
        result = await netmiko.merge_config(
            host=host,
            network_driver=device.network_driver,
            platform=device.platform,
            username=username,
            password=password,
            source_filename=parsed.source_filename,
            device_type=device_type,
            credential_reference=parsed.credential_reference,
            read_timeout=parsed.read_timeout,
        )
    except Exception as exc:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code=type(exc).__name__.lower(),
            message=str(exc),
        )

    answered = list(result.confirmed_prompts)
    if answered:
        logger.warning(
            "%s auto-answered %d interactive prompt(s) run_id=%s node_id=%s "
            "device_id=%s cues=%s",
            _STEP_ID,
            len(answered),
            run_id,
            node_id,
            device_id,
            answered,
        )

    output = result.output or ""
    output_ref = await artifact_service.store(
        content=output,
        kind=_ARTIFACT_KIND,
        device_id=device_id,
        run_id=context_run_id,
        media_type="text/plain",
    )
    summary = f"{len(output.encode('utf-8'))} bytes"
    if answered:
        summary += f" · {len(answered)} interactive prompt(s) auto-answered"

    step_result = CommandResult(
        node_id=node_id,
        command=command,
        success=result.success,
        output_ref=output_ref,
        summary=summary,
    )
    updated_command_results = dict(device.command_results)
    updated_command_results[node_id] = [step_result]

    if not result.success:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="merge_failed",
            message=result.error or f"{command!r} failed",
            command_results=updated_command_results,
        )

    enriched = device.model_copy(
        update={"status": DeviceStatus.OK, "command_results": updated_command_results}
    )
    return device_id, enriched, True


async def _merge_on_device_logged(
    *,
    index: int,
    total: int,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    run_id: Any,
    context_run_id: str,
    parsed: _ParsedMergeConfig,
    username: str,
    password: str,
    netmiko: NetmikoService,
    artifact_service: ArtifactService,
) -> tuple[str, DeviceContext, bool]:
    host = bare_hostname(device.primary_ip4, device.hostname) or "(no host)"
    logger.info(
        "%s device %d/%d id=%s host=%s: connecting run_id=%s",
        _STEP_ID,
        index,
        total,
        device_id,
        host,
        run_id,
    )
    result = await _merge_on_device(
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
    logger.info(
        "%s device %d/%d id=%s host=%s: %s run_id=%s",
        _STEP_ID,
        index,
        total,
        device_id,
        host,
        "ok" if result[2] else "failed",
        run_id,
    )
    return result


def _partition(
    results: list[tuple[str, DeviceContext, bool]],
) -> tuple[dict[str, DeviceContext], dict[str, DeviceContext]]:
    success: dict[str, DeviceContext] = {}
    failed: dict[str, DeviceContext] = {}
    for device_id, updated_device, ok in results:
        (success if ok else failed)[device_id] = updated_device
    return success, failed


def _build_outcomes(
    *,
    context: WorkflowContext,
    success_devices: dict[str, DeviceContext],
    failed_devices: dict[str, DeviceContext],
    source_filename: str,
) -> list[StepOutcome]:
    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": success_devices}),
            summary=(
                f"merged {source_filename} into running-config on "
                f"{len(success_devices)} device(s)"
            ),
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

    parsed = replace(
        _parse_merge_config(config),
        credential_reference=resolve_config_reference(
            config,
            source_key="credential_source",
            param_key="credential_param",
            literal_key="credential_reference",
            run_inputs=run.run_inputs,
        ),
    )

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")

    username, password = resolve_ssh_credential(
        db, parsed.credential_reference, acting_user_id=run.triggered_by_id
    )
    netmiko = NetmikoService(pool=device_sessions)
    total = len(context.devices)

    logger.info(
        "%s run_id=%s devices=%d credential=%s source_filename=%s override=%s read_timeout=%d",
        _STEP_ID,
        run.id,
        total,
        parsed.credential_reference,
        parsed.source_filename,
        parsed.network_driver_override,
        parsed.read_timeout,
    )

    results = await asyncio.gather(
        *[
            _merge_on_device_logged(
                index=index,
                total=total,
                device_id=device_id,
                device=device,
                node_id=node_id,
                run_id=run.id,
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
    success_devices, failed_devices = _partition(results)

    logger.info(
        "%s finished success=%d failure=%d run_id=%s",
        _STEP_ID,
        len(success_devices),
        len(failed_devices),
        run.id,
    )

    return _build_outcomes(
        context=context,
        success_devices=success_devices,
        failed_devices=failed_devices,
        source_filename=parsed.source_filename,
    )
