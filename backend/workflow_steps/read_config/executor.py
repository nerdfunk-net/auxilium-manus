"""Executor for the read-config step."""

from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
from services.workflow_context.device_template import (
    TemplateRenderOptions,
    render_device_template,
)
from workflow_steps.common.file_source_root import resolve_source_root
from workflow_steps.common.git_repository_loader import parse_repository_id
from workflow_steps.common.partial_outcomes import device_error_from_exception
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.common.step_flags import parse_bool_flag

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "read-config"
_SOURCES = frozenset({"filesystem", "git"})


@dataclass(frozen=True)
class _ParsedReadConfig:
    source: str
    git_repository_id: int | None
    path_template: str
    overwrite_existing: bool


def _parse_read_config(config: dict[str, Any]) -> _ParsedReadConfig:
    source = str(config.get("source") or "filesystem").strip().lower()
    if source not in _SOURCES:
        raise ValueError(f"{_STEP_ID}: source must be one of {sorted(_SOURCES)}")

    raw_repository_id = config.get("git_repository_id")
    git_repository_id = parse_repository_id(raw_repository_id, step_id=_STEP_ID)
    if source == "git" and git_repository_id is None:
        raise ValueError(f"{_STEP_ID}: git_repository_id is required when source=git")

    path_template = str(config.get("path_template") or "").strip()
    if not path_template:
        raise ValueError(f"{_STEP_ID}: path_template is required")

    return _ParsedReadConfig(
        source=source,
        git_repository_id=git_repository_id,
        path_template=path_template,
        overwrite_existing=parse_bool_flag(config, "overwrite_existing"),
    )


def _resolve_target_path(root: Path, relative_path: str) -> Path:
    root = root.resolve()
    target = (root / relative_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{_STEP_ID}: unsafe path {relative_path!r}") from exc
    return target


def _fail_device(
    *, device: DeviceContext, device_id: str, node_id: str, code: str, message: str
) -> tuple[str, DeviceContext, bool]:
    err = DeviceError(node_id=node_id, step_id=_STEP_ID, code=code, message=message)
    failed = device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, err]}
    )
    return device_id, failed, False


async def _read_for_device(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    root: Path,
    parsed: _ParsedReadConfig,
    context_run_id: str,
    artifact_service: ArtifactService,
) -> tuple[str, DeviceContext, bool]:
    if device.running_config_ref is not None and not parsed.overwrite_existing:
        return device_id, device, True

    try:
        relative_path = render_device_template(
            parsed.path_template,
            device,
            options=TemplateRenderOptions(strict=True, run_id=context_run_id),
        )
        target = _resolve_target_path(root, relative_path)
        if not target.is_file():
            raise FileNotFoundError(f"config file not found: {relative_path}")

        content = await asyncio.to_thread(target.read_text, encoding="utf-8")
        ref = await artifact_service.store(
            content=content,
            kind="running_config",
            device_id=device_id,
            run_id=context_run_id,
        )
        enriched = device.model_copy(
            update={
                "status": DeviceStatus.OK,
                "running_config_ref": ref,
                "capabilities": device.capabilities | {Capability.RUNNING_CONFIG},
            }
        )
        return device_id, enriched, True
    except Exception as exc:
        # ``ValueError``/``FileNotFoundError`` text is written by this step (relative paths);
        # an ``OSError`` such as ``PermissionError`` carries the absolute path: class name only.
        error = device_error_from_exception(exc, node_id=node_id, step_id=_STEP_ID)
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code=error.code,
            message=error.message,
        )


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
    context: WorkflowContext,
    success_devices: dict[str, DeviceContext],
    failed_devices: dict[str, DeviceContext],
) -> list[StepOutcome]:
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


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del device_sessions  # unused: this step never connects to a device

    parsed = _parse_read_config(config)

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    logger.info(
        "read-config started run_id=%s node_id=%s devices=%d source=%s",
        log_run_id(run),
        node_id,
        len(context.devices),
        parsed.source,
    )

    async with AsyncExitStack() as stack:
        root = await resolve_source_root(
            source=parsed.source,
            git_repository_id=parsed.git_repository_id,
            stack=stack,
            allow_stale=parse_bool_flag(config, "allow_stale_repository"),
            step_id=_STEP_ID,
        )

        results = await asyncio.gather(
            *[
                _read_for_device(
                    device_id=device_id,
                    device=device,
                    node_id=node_id,
                    root=root,
                    parsed=parsed,
                    context_run_id=context.run_id,
                    artifact_service=artifact_service,
                )
                for device_id, device in context.devices.items()
            ]
        )
    success_devices, failed_devices = _partition_device_results(results)

    logger.info(
        "read-config finished success=%d failure=%d run_id=%s",
        len(success_devices),
        len(failed_devices),
        log_run_id(run),
    )
    return _build_outcomes(context, success_devices, failed_devices)
