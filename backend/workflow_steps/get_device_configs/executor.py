"""Executor for the get-device-configs step."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy.orm import object_session

from core.models.runs import WorkflowRun
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
    bare_hostname,
)
from services.artifacts import ArtifactService
from services.network.netmiko.service import NetmikoService
from workflow_steps.common.credential_resolver import resolve_ssh_credential

logger = logging.getLogger(__name__)

_CONFIG_FORMATS = frozenset({"running", "startup", "both"})


def _config_targets(config_format: str) -> tuple[bool, bool]:
    normalized = config_format.strip().lower()
    if normalized == "running":
        return True, False
    if normalized == "startup":
        return False, True
    return True, True


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
    config_format = str(config.get("config_format") or "both").strip().lower()
    if config_format not in _CONFIG_FORMATS:
        raise ValueError(
            f"get-device-configs: config_format must be one of {sorted(_CONFIG_FORMATS)}"
        )

    db = object_session(run)
    if db is None:
        raise RuntimeError("get-device-configs: WorkflowRun has no active DB session")

    username, password = resolve_ssh_credential(db, credential_reference)
    include_running, include_startup = _config_targets(config_format)
    netmiko = NetmikoService()

    logger.info(
        "get-device-configs run_id=%s devices=%d credential=%s format=%s",
        run.id,
        len(context.devices),
        credential_reference,
        config_format,
    )

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}

    async def fetch_device(
        device_id: str,
        device: DeviceContext,
    ) -> tuple[str, DeviceContext, bool]:
        host = bare_hostname(device.primary_ip4, device.hostname)
        if not host:
            err = DeviceError(
                node_id=node_id,
                step_id="get-device-configs",
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

        try:
            result = await netmiko.get_configs(
                host=host,
                network_driver=device.network_driver,
                platform=device.platform,
                username=username,
                password=password,
                include_running=include_running,
                include_startup=include_startup,
            )
            if not result.success:
                raise RuntimeError(result.error or "Config retrieval failed")

            updates: dict[str, Any] = {
                "status": DeviceStatus.OK,
                "capabilities": set(device.capabilities),
            }

            if include_running and result.running_config is not None:
                running_ref = await artifact_service.store(
                    content=result.running_config,
                    kind="running_config",
                    device_id=device_id,
                    run_id=context.run_id,
                )
                updates["running_config_ref"] = running_ref
                updates["capabilities"] = updates["capabilities"] | {Capability.RUNNING_CONFIG}

            if include_startup and result.startup_config is not None:
                startup_ref = await artifact_service.store(
                    content=result.startup_config,
                    kind="startup_config",
                    device_id=device_id,
                    run_id=context.run_id,
                )
                updates["startup_config_ref"] = startup_ref
                updates["capabilities"] = updates["capabilities"] | {
                    Capability.STARTUP_CONFIG
                }

            enriched = device.model_copy(update=updates)
            return device_id, enriched, True
        except Exception as exc:
            err = DeviceError(
                node_id=node_id,
                step_id="get-device-configs",
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

    async def fetch_device_logged(
        index: int, device_id: str, device: DeviceContext
    ) -> tuple[str, DeviceContext, bool]:
        host = bare_hostname(device.primary_ip4, device.hostname) or "(no host)"
        total = len(context.devices)
        logger.info(
            "get-device-configs device %d/%d id=%s host=%s: connecting run_id=%s",
            index,
            total,
            device_id,
            host,
            run.id,
        )
        result = await fetch_device(device_id, device)
        _, _, ok = result
        logger.info(
            "get-device-configs device %d/%d id=%s host=%s: %s run_id=%s",
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
            fetch_device_logged(index, device_id, device)
            for index, (device_id, device) in enumerate(context.devices.items(), start=1)
        ]
    )

    for device_id, updated_device, ok in results:
        if ok:
            success_devices[device_id] = updated_device
        else:
            failed_devices[device_id] = updated_device

    logger.info(
        "get-device-configs returning %d/%d devices run_id=%s",
        len(success_devices),
        len(context.devices),
        run.id,
    )

    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": success_devices}),
        )
    ]
    if failed_devices:
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(update={"devices": failed_devices}),
            )
        )
    return outcomes
