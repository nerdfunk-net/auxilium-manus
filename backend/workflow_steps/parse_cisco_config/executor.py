"""Executor for the parse-cisco-config step."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.failure import FailureInfo
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.network.cisco_config_parsing import (
    parse_cisco_config_text,
    platform_hint_for_network_driver,
)
from workflow_steps.common.device_outcomes import fail_device_with_error
from workflow_steps.common.partial_outcomes import device_error_from_exception
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.common.step_flags import parse_output_key
from workflow_steps.parse_cisco_config.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_CONFIG_SOURCES = frozenset({"running", "startup", "both"})
_STEP_ID = "parse-cisco-config"


class _DeviceConfigError(ValueError):
    """A condition of this device with a sentence written here (safe to keep) and its record."""

    def __init__(self, message: str, failure: FailureInfo) -> None:
        super().__init__(message)
        self.failure = failure


_BAD_INPUT = FailureInfo(phase="config", kind="bad_request")


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


def _platform_hint(device: DeviceContext, network_driver_override: str | None) -> str | None:
    return platform_hint_for_network_driver(network_driver_override or device.network_driver)


def _build_parse_entry(
    running_model: dict[str, Any] | None,
    startup_model: dict[str, Any] | None,
) -> dict[str, Any]:
    """Assemble the parsed-config entry stored at ``device.parsed[output_key]``.

    The shape is **always** ``{"running": ..., "startup": ...}`` regardless of
    ``config_source``; the branch not requested by ``config_source`` stays
    ``None``. This mirrors ``preview_service.get_configs()`` so downstream
    templates and steps use one stable path (``parsed.<key>.running.*`` /
    ``parsed.<key>.startup.*``) and the template-editor preview matches a run.
    """
    return {"running": running_model, "startup": startup_model}


async def _parse_text(
    text: str, platform_hint: str | None, device: DeviceContext
) -> dict[str, Any]:
    """Parse off the event loop; a parser ``ValueError`` (its text can quote config lines) becomes
    a fixed sentence, an unknown platform names the fix instead of the library's banner."""
    try:
        return await asyncio.to_thread(parse_cisco_config_text, text, platform_hint)
    except ValueError as exc:
        if platform_hint is None:
            raise _DeviceConfigError(
                f"{_STEP_ID}: cannot determine the platform of {device.name} "
                f"(network_driver={device.network_driver!r}); set network_driver_override",
                FailureInfo(phase="config", kind="unsupported_platform"),
            ) from exc
        raise _DeviceConfigError(
            f"{_STEP_ID}: the configuration could not be parsed ({type(exc).__name__})",
            _BAD_INPUT,
        ) from exc


async def _parse_one_device(
    *,
    device_id: str,
    device: DeviceContext,
    artifact_service: ArtifactService,
    run_id: Any,
    node_id: str,
    need_running: bool,
    need_startup: bool,
    output_key: str,
    network_driver_override: str | None,
) -> tuple[str, DeviceContext, bool]:
    platform_hint = _platform_hint(device, network_driver_override)
    try:
        running_model: dict[str, Any] | None = None
        startup_model: dict[str, Any] | None = None

        if need_running:
            if device.running_config_ref is None:
                raise _DeviceConfigError(
                    "running config is not available on this device — add a "
                    "Get Configs step upstream with running config enabled",
                    _BAD_INPUT,
                )
            running_text = await artifact_service.resolve(device.running_config_ref)
            running_model = await _parse_text(running_text, platform_hint, device)

        if need_startup:
            if device.startup_config_ref is None:
                raise _DeviceConfigError(
                    "startup config is not available on this device — add a "
                    "Get Configs step upstream with startup config enabled",
                    _BAD_INPUT,
                )
            startup_text = await artifact_service.resolve(device.startup_config_ref)
            startup_model = await _parse_text(startup_text, platform_hint, device)

        entry = _build_parse_entry(running_model, startup_model)
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
        # The class name only: parser and driver text can quote config lines.
        logger.warning(
            "parse-cisco-config failed run_id=%s node_id=%s device_id=%s error=%s",
            run_id,
            node_id,
            device_id,
            type(exc).__name__,
        )
        if isinstance(exc, _DeviceConfigError):
            err = DeviceError(
                node_id=node_id,
                step_id=_STEP_ID,
                code="config_error",
                message=str(exc),
                failure=exc.failure,
            )
        else:
            err = device_error_from_exception(exc, node_id=node_id, step_id=_STEP_ID)
        failed = fail_device_with_error(device, err)
        return device_id, failed, False


def _partition_parse_results(
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


def _build_parse_outcomes(
    *,
    context: WorkflowContext,
    node_id: str,
    run_id: Any,
    success_devices: dict[str, DeviceContext],
    failed_devices: dict[str, DeviceContext],
) -> list[StepOutcome]:
    metadata = {
        **context.metadata,
        f"{node_id}.parse_success_count": len(success_devices),
        f"{node_id}.parse_failure_count": len(failed_devices),
    }

    logger.info(
        "parse-cisco-config finished success=%d failure=%d run_id=%s",
        len(success_devices),
        len(failed_devices),
        run_id,
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


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    config_source = _parse_config_source(config)
    output_key = parse_output_key(config.get("output_key") or get_config()["output_key"])
    need_running, need_startup = _config_targets(config_source)
    network_driver_override = str(config.get("network_driver_override") or "").strip() or None
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    logger.info(
        "parse-cisco-config started run_id=%s node_id=%s devices=%d config_source=%s output_key=%s",
        log_run_id(run),
        node_id,
        len(context.devices),
        config_source,
        output_key,
    )

    results = await asyncio.gather(
        *[
            _parse_one_device(
                device_id=device_id,
                device=device,
                artifact_service=artifact_service,
                run_id=log_run_id(run),
                node_id=node_id,
                need_running=need_running,
                need_startup=need_startup,
                output_key=output_key,
                network_driver_override=network_driver_override,
            )
            for device_id, device in context.devices.items()
        ]
    )
    success_devices, failed_devices = _partition_parse_results(results)
    return _build_parse_outcomes(
        context=context,
        node_id=node_id,
        run_id=log_run_id(run),
        success_devices=success_devices,
        failed_devices=failed_devices,
    )
