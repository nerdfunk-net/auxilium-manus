"""Executor for the deploy-rendered-template step."""

from __future__ import annotations

import asyncio
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
from workflow_steps.common.content_resolver import list_exportable_content
from workflow_steps.common.credential_resolver import resolve_ssh_credential

logger = logging.getLogger(__name__)

_EXECUTION_MODES = {"config_mode", "exec_mode"}


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


def _parse_write_config(config: dict[str, Any]) -> bool:
    value = config.get("write_config_after_execution", False)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


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
    source_step_node_id = str(config.get("source_step_node_id") or "").strip()
    parsed_output_key = str(config.get("parsed_output_key") or "").strip() or None
    network_driver_override = str(config.get("network_driver_override") or "").strip() or None
    execution_mode = _parse_execution_mode(config)
    write_config_after_execution = _parse_write_config(config)

    if not source_step_node_id:
        raise ValueError("deploy-rendered-template: source_step_node_id is required")

    db = object_session(run)
    if db is None:
        raise RuntimeError("deploy-rendered-template: WorkflowRun has no active DB session")

    username, password = resolve_ssh_credential(db, credential_reference)
    netmiko = NetmikoService()

    logger.info(
        "deploy-rendered-template started run_id=%s node_id=%s devices=%d credential=%s "
        "source=%s mode=%s write_config=%s override=%s",
        run.id,
        node_id,
        len(context.devices),
        credential_reference,
        source_step_node_id,
        execution_mode,
        write_config_after_execution,
        network_driver_override,
    )

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}

    def _fail(
        device: DeviceContext, device_id: str, code: str, message: str
    ) -> tuple[str, DeviceContext, bool]:
        err = DeviceError(
            node_id=node_id,
            step_id="deploy-rendered-template",
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

    async def deploy_on_device(
        device_id: str,
        device: DeviceContext,
    ) -> tuple[str, DeviceContext, bool]:
        host = bare_hostname(device.primary_ip4, device.hostname)
        if not host:
            return _fail(
                device,
                device_id,
                "missing_host",
                f"Device {device_id} has no hostname or primary IP",
            )

        items = list_exportable_content(
            device,
            content_source="rendered_template",
            source_step_node_id=source_step_node_id,
            parsed_output_key=parsed_output_key,
        )
        if not items:
            return _fail(
                device,
                device_id,
                "rendered_template_missing",
                "No rendered template found for the configured source step",
            )

        rendered_text = await artifact_service.resolve(items[0].artifact_ref)
        commands = [line for line in rendered_text.splitlines() if line.strip()]
        if not commands:
            return _fail(
                device,
                device_id,
                "empty_rendered_template",
                "Rendered template produced no commands",
            )

        device_type = resolve_connection_device_type(
            network_driver=device.network_driver,
            platform=device.platform,
            override=network_driver_override,
        )

        try:
            result = await netmiko.deploy_config(
                host=host,
                network_driver=device.network_driver,
                platform=device.platform,
                username=username,
                password=password,
                commands=commands,
                mode=execution_mode,
                write_config=write_config_after_execution,
                device_type=device_type,
            )

            step_results: list[CommandResult] = []
            output_ref = await artifact_service.store(
                content=result.config_output,
                kind="command_output",
                device_id=device_id,
                run_id=context.run_id,
            )
            step_results.append(
                CommandResult(
                    node_id=node_id,
                    command="deploy-rendered-template",
                    success=result.success,
                    output_ref=output_ref,
                    summary=f"{len(commands)} line(s) deployed ({execution_mode})",
                )
            )
            if result.save_output is not None:
                save_ref = await artifact_service.store(
                    content=result.save_output,
                    kind="command_output",
                    device_id=device_id,
                    run_id=context.run_id,
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

            updated_command_results = dict(device.command_results)
            updated_command_results[node_id] = step_results

            if not result.success:
                err = DeviceError(
                    node_id=node_id,
                    step_id="deploy-rendered-template",
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
        except Exception as exc:
            return _fail(device, device_id, type(exc).__name__.lower(), str(exc))

    async def deploy_on_device_logged(
        index: int, device_id: str, device: DeviceContext
    ) -> tuple[str, DeviceContext, bool]:
        host = bare_hostname(device.primary_ip4, device.hostname) or "(no host)"
        total = len(context.devices)
        logger.info(
            "deploy-rendered-template device %d/%d id=%s host=%s: connecting run_id=%s",
            index,
            total,
            device_id,
            host,
            run.id,
        )
        result = await deploy_on_device(device_id, device)
        _, _, ok = result
        logger.info(
            "deploy-rendered-template device %d/%d id=%s host=%s: %s run_id=%s",
            index,
            total,
            device_id,
            host,
            "ok" if ok else "failed",
            run.id,
        )
        return result

    results = await asyncio.gather(
        *[
            deploy_on_device_logged(index, device_id, device)
            for index, (device_id, device) in enumerate(context.devices.items(), start=1)
        ]
    )

    for device_id, updated_device, ok in results:
        if ok:
            success_devices[device_id] = updated_device
        else:
            failed_devices[device_id] = updated_device

    logger.info(
        "deploy-rendered-template finished success=%d failure=%d run_id=%s",
        len(success_devices),
        len(failed_devices),
        run.id,
    )

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
