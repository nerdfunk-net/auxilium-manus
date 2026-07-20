"""Executor for the parse-cisco-config step."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from cisco_config_parser import ConfigParser

from core.models.runs import WorkflowRun
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from workflow_steps.common.jinja_render import parse_output_key
from workflow_steps.parse_cisco_config.config import get_config

logger = logging.getLogger(__name__)

_CONFIG_SOURCES = frozenset({"running", "startup", "both"})

# cisco-config-parser's Parser._normalize_platform() lower-cases and looks
# this up in its own PLATFORM_ALIASES map, so passing "IOS"/"NXOS"/"XR"
# directly (rather than the Netmiko-style driver name) is accepted.
_NETWORK_DRIVER_PLATFORM_HINTS = {
    "cisco_ios": "IOS",
    "cisco_xe": "IOS",
    "cisco_ios_xe": "IOS",
    "cisco_nxos": "NXOS",
    "cisco_xr": "XR",
    "cisco_ios_xr": "XR",
}


def _parse_config_source(config: dict[str, Any]) -> str:
    raw = str(config.get("config_source") or get_config()["config_source"]).strip().lower()
    if raw not in _CONFIG_SOURCES:
        raise ValueError(
            f"parse-cisco-config: config_source must be one of {sorted(_CONFIG_SOURCES)}, "
            f"got {raw!r}"
        )
    return raw


def _config_targets(config_source: str) -> tuple[bool, bool]:
    if config_source == "running":
        return True, False
    if config_source == "startup":
        return False, True
    return True, True


def _platform_hint(device: DeviceContext) -> str | None:
    return _NETWORK_DRIVER_PLATFORM_HINTS.get((device.network_driver or "").strip().lower())


def _parse_config_text(content: str, platform_hint: str | None) -> dict[str, Any]:
    return ConfigParser(content, platform=platform_hint).parse()


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

    config_source = _parse_config_source(config)
    output_key = parse_output_key(config.get("output_key") or get_config()["output_key"])
    need_running, need_startup = _config_targets(config_source)

    logger.info(
        "parse-cisco-config started run_id=%s node_id=%s devices=%d config_source=%s "
        "output_key=%s",
        run.id,
        node_id,
        len(context.devices),
        config_source,
        output_key,
    )

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}

    async def parse_device(
        device_id: str,
        device: DeviceContext,
    ) -> tuple[str, DeviceContext, bool]:
        platform_hint = _platform_hint(device)
        try:
            running_model: dict[str, Any] | None = None
            startup_model: dict[str, Any] | None = None

            if need_running:
                if device.running_config_ref is None:
                    raise ValueError(
                        "running config is not available on this device — add a "
                        "Get Configs step upstream with running config enabled"
                    )
                running_text = await artifact_service.resolve(device.running_config_ref)
                running_model = _parse_config_text(running_text, platform_hint)

            if need_startup:
                if device.startup_config_ref is None:
                    raise ValueError(
                        "startup config is not available on this device — add a "
                        "Get Configs step upstream with startup config enabled"
                    )
                startup_text = await artifact_service.resolve(device.startup_config_ref)
                startup_model = _parse_config_text(startup_text, platform_hint)

            if config_source == "both":
                entry: dict[str, Any] | None = {
                    "running": running_model,
                    "startup": startup_model,
                }
            elif config_source == "running":
                entry = running_model
            else:
                entry = startup_model

            parsed = dict(device.parsed)
            parsed[output_key] = entry
            enriched = device.model_copy(
                update={
                    "parsed": parsed,
                    "capabilities": device.capabilities | {Capability.PARSED},
                    "status": DeviceStatus.OK,
                }
            )
            return device_id, enriched, True
        except Exception as exc:
            logger.warning(
                "parse-cisco-config failed run_id=%s node_id=%s device_id=%s error=%s",
                run.id,
                node_id,
                device_id,
                exc,
            )
            err = DeviceError(
                node_id=node_id,
                step_id="parse-cisco-config",
                code="config_error" if isinstance(exc, ValueError) else type(exc).__name__.lower(),
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
        *[parse_device(device_id, device) for device_id, device in context.devices.items()]
    )

    for device_id, updated_device, ok in results:
        if ok:
            success_devices[device_id] = updated_device
        else:
            failed_devices[device_id] = updated_device

    metadata = {
        **context.metadata,
        f"{node_id}.parse_success_count": len(success_devices),
        f"{node_id}.parse_failure_count": len(failed_devices),
    }

    logger.info(
        "parse-cisco-config finished success=%d failure=%d run_id=%s",
        len(success_devices),
        len(failed_devices),
        run.id,
    )

    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": success_devices, "metadata": metadata}),
        )
    ]
    if failed_devices:
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(
                    update={"devices": failed_devices, "metadata": metadata}
                ),
            )
        )
    return outcomes
