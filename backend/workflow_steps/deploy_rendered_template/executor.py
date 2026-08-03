"""Executor for the deploy-rendered-template step."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
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
from workflow_steps.common.content_resolver import list_exportable_content
from workflow_steps.common.credential_resolver import resolve_ssh_credential

logger = logging.getLogger(__name__)

_STEP_ID = "deploy-rendered-template"
_EXECUTION_MODES = {"config_mode", "exec_mode"}
_MIN_READ_TIMEOUT = 5
_MAX_READ_TIMEOUT = 600


@dataclass(frozen=True)
class _ParsedDeployConfig:
    credential_reference: str
    source_step_node_id: str
    parsed_output_key: str | None
    network_driver_override: str | None
    execution_mode: str
    write_config_after_execution: bool
    read_timeout: int
    auto_confirm_prompts: bool


def _default_config() -> dict[str, Any]:
    from workflow_steps.deploy_rendered_template.config import get_config

    return get_config()


def _parse_execution_mode(config: dict[str, Any]) -> str:
    mode = str(config.get("execution_mode") or _default_config()["execution_mode"]).strip().lower()
    if mode not in _EXECUTION_MODES:
        raise ValueError(
            f"deploy-rendered-template: execution_mode must be one of {sorted(_EXECUTION_MODES)}"
        )
    return mode


def _parse_read_timeout(config: dict[str, Any]) -> int:
    raw = config.get("read_timeout")
    if raw in (None, ""):
        raw = _default_config()["read_timeout"]
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("deploy-rendered-template: read_timeout must be an integer") from exc
    if not (_MIN_READ_TIMEOUT <= value <= _MAX_READ_TIMEOUT):
        raise ValueError(
            f"deploy-rendered-template: read_timeout must be between {_MIN_READ_TIMEOUT} "
            f"and {_MAX_READ_TIMEOUT} seconds"
        )
    return value


def _parse_write_config(config: dict[str, Any]) -> bool:
    value = config.get("write_config_after_execution", False)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _parse_auto_confirm_prompts(config: dict[str, Any]) -> bool:
    value = config.get("auto_confirm_prompts", False)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _parse_deploy_config(config: dict[str, Any]) -> _ParsedDeployConfig:
    source_step_node_id = str(config.get("source_step_node_id") or "").strip()
    if not source_step_node_id:
        raise ValueError("deploy-rendered-template: source_step_node_id is required")

    return _ParsedDeployConfig(
        credential_reference=str(config.get("credential_reference") or "").strip(),
        source_step_node_id=source_step_node_id,
        parsed_output_key=str(config.get("parsed_output_key") or "").strip() or None,
        network_driver_override=str(config.get("network_driver_override") or "").strip() or None,
        execution_mode=_parse_execution_mode(config),
        write_config_after_execution=_parse_write_config(config),
        read_timeout=_parse_read_timeout(config),
        auto_confirm_prompts=_parse_auto_confirm_prompts(config),
    )


def _fail_device(
    *,
    device: DeviceContext,
    device_id: str,
    node_id: str,
    code: str,
    message: str,
) -> tuple[str, DeviceContext, bool]:
    err = DeviceError(
        node_id=node_id,
        step_id=_STEP_ID,
        code=code,
        message=message,
    )
    failed = device.model_copy(
        update={
            "status": DeviceStatus.FAILED,
            "errors": [*device.errors, err],
        }
    )
    return device_id, failed, False


async def _load_deploy_commands(
    *,
    device: DeviceContext,
    device_id: str,
    node_id: str,
    parsed: _ParsedDeployConfig,
    artifact_service: ArtifactService,
) -> list[str] | tuple[str, DeviceContext, bool]:
    items = list_exportable_content(
        device,
        content_source="rendered_template",
        source_step_node_id=parsed.source_step_node_id,
        parsed_output_key=parsed.parsed_output_key,
    )
    if not items:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="rendered_template_missing",
            message="No rendered template found for the configured source step",
        )
    rendered_text = await artifact_service.resolve(items[0].artifact_ref)
    commands = [line for line in rendered_text.splitlines() if line.strip()]
    if not commands:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="empty_rendered_template",
            message="Rendered template produced no commands",
        )
    return commands


async def _run_deploy_config(
    *,
    host: str,
    device: DeviceContext,
    device_id: str,
    node_id: str,
    run_id: Any,
    parsed: _ParsedDeployConfig,
    username: str,
    password: str,
    commands: list[str],
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
        commands=commands,
        mode=parsed.execution_mode,
        write_config=parsed.write_config_after_execution,
        device_type=device_type,
        read_timeout=parsed.read_timeout,
        auto_confirm_prompts=parsed.auto_confirm_prompts,
        credential_reference=parsed.credential_reference,
    )
    if result.confirmed_prompts:
        logger.warning(
            "deploy-rendered-template auto-confirmed %d prompt(s) run_id=%s "
            "node_id=%s device_id=%s commands=%s",
            len(result.confirmed_prompts),
            run_id,
            node_id,
            device_id,
            result.confirmed_prompts,
        )
    return result


async def _store_deploy_command_results(
    *,
    result: Any,
    commands: list[str],
    device_id: str,
    node_id: str,
    context_run_id: str | None,
    parsed: _ParsedDeployConfig,
    artifact_service: ArtifactService,
) -> list[CommandResult]:
    step_results: list[CommandResult] = []
    output_ref = await artifact_service.store(
        content=result.config_output,
        kind="command_output",
        device_id=device_id,
        run_id=context_run_id,
    )
    summary = f"{len(commands)} line(s) deployed ({parsed.execution_mode})"
    if result.confirmed_prompts:
        summary += (
            f" · {len(result.confirmed_prompts)} confirmation prompt(s) auto-confirmed"
        )
    step_results.append(
        CommandResult(
            node_id=node_id,
            command="deploy-rendered-template",
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


def _apply_deploy_result(
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
        err = DeviceError(
            node_id=node_id,
            step_id=_STEP_ID,
            code="deploy_failed",
            message=result.error or "Deploying rendered template failed",
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


async def _deploy_on_device(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    run_id: Any,
    context_run_id: str | None,
    parsed: _ParsedDeployConfig,
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

    loaded = await _load_deploy_commands(
        device=device,
        device_id=device_id,
        node_id=node_id,
        parsed=parsed,
        artifact_service=artifact_service,
    )
    if isinstance(loaded, tuple):
        return loaded

    try:
        result = await _run_deploy_config(
            host=host,
            device=device,
            device_id=device_id,
            node_id=node_id,
            run_id=run_id,
            parsed=parsed,
            username=username,
            password=password,
            commands=loaded,
            netmiko=netmiko,
        )
        step_results = await _store_deploy_command_results(
            result=result,
            commands=loaded,
            device_id=device_id,
            node_id=node_id,
            context_run_id=context_run_id,
            parsed=parsed,
            artifact_service=artifact_service,
        )
        return _apply_deploy_result(
            device=device,
            device_id=device_id,
            node_id=node_id,
            result=result,
            step_results=step_results,
        )
    except Exception as exc:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code=type(exc).__name__.lower(),
            message=str(exc),
        )


async def _deploy_on_device_logged(
    *,
    index: int,
    device_id: str,
    device: DeviceContext,
    total: int,
    run_id: Any,
    node_id: str,
    context_run_id: str | None,
    parsed: _ParsedDeployConfig,
    username: str,
    password: str,
    netmiko: NetmikoService,
    artifact_service: ArtifactService,
) -> tuple[str, DeviceContext, bool]:
    host = bare_hostname(device.primary_ip4, device.hostname) or "(no host)"
    logger.info(
        "deploy-rendered-template device %d/%d id=%s host=%s: connecting run_id=%s",
        index,
        total,
        device_id,
        host,
        run_id,
    )
    result = await _deploy_on_device(
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
        "deploy-rendered-template device %d/%d id=%s host=%s: %s run_id=%s",
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


def _build_deploy_outcomes(
    *,
    context: WorkflowContext,
    success_devices: dict[str, DeviceContext],
    failed_devices: dict[str, DeviceContext],
) -> list[StepOutcome]:
    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": success_devices}),
            summary=f"deployed rendered template to {len(success_devices)} device(s)",
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

    parsed = _parse_deploy_config(config)

    db = object_session(run)
    if db is None:
        raise RuntimeError("deploy-rendered-template: WorkflowRun has no active DB session")

    username, password = resolve_ssh_credential(
        db, parsed.credential_reference, acting_user_id=run.triggered_by_id
    )
    netmiko = NetmikoService(pool=device_sessions)
    total = len(context.devices)

    logger.info(
        "deploy-rendered-template started run_id=%s node_id=%s devices=%d credential=%s "
        "source=%s mode=%s write_config=%s override=%s read_timeout=%d "
        "auto_confirm_prompts=%s",
        run.id,
        node_id,
        total,
        parsed.credential_reference,
        parsed.source_step_node_id,
        parsed.execution_mode,
        parsed.write_config_after_execution,
        parsed.network_driver_override,
        parsed.read_timeout,
        parsed.auto_confirm_prompts,
    )

    results = await asyncio.gather(
        *[
            _deploy_on_device_logged(
                index=index,
                device_id=device_id,
                device=device,
                total=total,
                run_id=run.id,
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

    success_devices, failed_devices = _partition_device_results(results)

    logger.info(
        "deploy-rendered-template finished success=%d failure=%d run_id=%s",
        len(success_devices),
        len(failed_devices),
        run.id,
    )

    return _build_deploy_outcomes(
        context=context,
        success_devices=success_devices,
        failed_devices=failed_devices,
    )
