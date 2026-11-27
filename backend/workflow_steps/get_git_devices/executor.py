"""Executor for the get-git-devices step."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.git.device_service import GitDeviceService
from workflow_steps.common.device_builders import device_context_from_git_detail
from workflow_steps.common.failure_records import INVALID_INPUT
from workflow_steps.common.fan_out import inventory_metadata
from workflow_steps.common.git_repository_loader import load_git_repository, require_repository_id
from workflow_steps.common.partial_outcomes import mark_device_failed
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.common.step_flags import parse_bool_flag
from workflow_steps.get_git_devices.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "get-git-devices"


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service  # unused for this step

    raw_repository_id = config.get("git_repository_id")
    filename_pattern = (config.get("filename_pattern") or "").strip()
    directory = (config.get("directory") or "").strip()

    if raw_repository_id in (None, ""):
        raise ValueError("get-git-devices: git_repository_id is not configured")
    if not filename_pattern:
        raise ValueError("get-git-devices: filename_pattern is not configured")
    git_repository_id = require_repository_id(raw_repository_id, step_id=_STEP_ID)

    logger.info(
        "get-git-devices started run_id=%s git_repository_id=%s filename_pattern=%s",
        log_run_id(run),
        git_repository_id,
        filename_pattern,
    )

    loop = asyncio.get_running_loop()
    repository = await loop.run_in_executor(None, lambda: load_git_repository(git_repository_id))

    service = GitDeviceService()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: service.fetch_records(
                repository,
                filename_pattern,
                directory,
                config.get("device_mapping"),
                file_format=str(config.get("file_format") or get_config()["file_format"]),
                csv_delimiter=str(config.get("csv_delimiter") or get_config()["csv_delimiter"]),
                csv_multiline=parse_bool_flag(config, "csv_multiline"),
            ),
        )
    except ValueError as exc:
        raise ValueError(f"get-git-devices: {exc}") from exc
    files_read = result.files_read

    if not result.records:
        detail = "; ".join(result.warnings) or "no device entries found"
        raise RuntimeError(f"get-git-devices: no devices found ({detail})")

    logger.info(
        "get-git-devices returning %d devices from %d file(s) run_id=%s",
        len(result.records),
        files_read,
        log_run_id(run),
    )

    new_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}
    for index, record in enumerate(result.records):
        device_ctx = device_context_from_git_detail(
            record.mapped,
            source_id=str(git_repository_id),
            index=index,
            raw=record.raw,
        )
        if record.problems:
            # A data problem in the file (e.g. two primary interfaces) fails this device only.
            for problem in record.problems:
                device_ctx = mark_device_failed(
                    device_ctx,
                    node_id=node_id,
                    step_id=_STEP_ID,
                    code=problem.code,
                    failure=INVALID_INPUT,
                    message=problem.message,
                )
            failed_devices[device_ctx.id] = device_ctx
        else:
            new_devices[device_ctx.id] = device_ctx

    metadata = inventory_metadata(
        context.metadata,
        node_id,
        config.get("fan_out"),
        git_repository_id=git_repository_id,
        total=len(new_devices) + len(failed_devices),
        failed=len(failed_devices),
        files_read=files_read,
        warnings=result.warnings,
    )
    if "_fan_out" in metadata.success and failed_devices:
        # The engine fans out from the success outcome only and seeds every child with it, so a
        # failure outcome would be dropped and its devices never reach a later step.
        codes = sorted({e.code for d in failed_devices.values() for e in d.errors})
        raise RuntimeError(
            f"get-git-devices: {len(failed_devices)} device(s) have invalid primary IP data "
            f"({', '.join(codes)}); the failure outcome is not available with fan-out enabled, "
            "fix the file or turn fan-out off"
        )

    new_context = context.model_copy(
        update={
            "devices": {**context.devices, **new_devices},
            "metadata": metadata.success,
        }
    )
    outcomes = [StepOutcome(name="success", context=new_context)]
    if failed_devices:
        # Only the failed devices travel on this path; the fan-out metadata stays on success.
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(
                    update={
                        "devices": failed_devices,
                        "metadata": metadata.base,
                    }
                ),
            )
        )
    return outcomes
