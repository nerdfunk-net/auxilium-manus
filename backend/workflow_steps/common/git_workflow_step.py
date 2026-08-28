"""Shared helpers for git workflow steps (clone, pull, push)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from core.models.runs import WorkflowRun
from models.workflow_context import (
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from workflow_steps.common.git_repository_loader import load_git_repository

logger = logging.getLogger(__name__)

GitOperation = Callable[
    [Any, dict[str, Any], dict[str, Any], WorkflowContext],
    dict[str, Any],
]


def _git_repository_id(config: dict[str, Any]) -> int | None:
    raw = config.get("git_repository_id")
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _metadata_key(node_id: str) -> str:
    return f"{node_id}.git_operation"


def _mark_devices_failed(
    *,
    devices: dict[str, DeviceContext],
    node_id: str,
    step_id: str,
    message: str,
) -> dict[str, DeviceContext]:
    error = DeviceError(
        node_id=node_id,
        step_id=step_id,
        code="git_operation_failed",
        message=message,
    )
    return {
        device_id: device.model_copy(
            update={
                "status": DeviceStatus.FAILED,
                "errors": [*device.errors, error],
            }
        )
        for device_id, device in devices.items()
    }


def _failure_outcomes(
    *,
    context: WorkflowContext,
    node_id: str,
    step_id: str,
    operation: str,
    git_repository_id: int | None,
    message: str,
) -> list[StepOutcome]:
    metadata = {
        **context.metadata,
        _metadata_key(node_id): {
            "success": False,
            "operation": operation,
            "git_repository_id": git_repository_id,
            "message": message,
        },
    }
    if context.devices:
        failed_devices = _mark_devices_failed(
            devices=context.devices,
            node_id=node_id,
            step_id=step_id,
            message=message,
        )
        return [
            StepOutcome(
                name="success",
                context=context.model_copy(update={"devices": {}, "metadata": metadata}),
            ),
            StepOutcome(
                name="failure",
                context=context.model_copy(
                    update={"devices": failed_devices, "metadata": metadata}
                ),
            ),
        ]

    return [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": {}, "metadata": metadata}),
        ),
        StepOutcome(
            name="failure",
            context=context.model_copy(update={"metadata": metadata}),
        ),
    ]


async def run_git_workflow_step(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    step_id: str,
    operation: GitOperation,
    operation_name: str,
) -> list[StepOutcome]:
    del run, artifact_service

    repository_id = _git_repository_id(config)
    if repository_id is None:
        message = f"{step_id}: git_repository_id is not configured"
        return _failure_outcomes(
            context=context,
            node_id=node_id,
            step_id=step_id,
            operation=operation_name,
            git_repository_id=repository_id,
            message=message,
        )

    logger.info("%s started run_id=%s repository_id=%s", step_id, context.run_id, repository_id)

    try:
        repository = load_git_repository(repository_id)
    except ValueError as exc:
        return _failure_outcomes(
            context=context,
            node_id=node_id,
            step_id=step_id,
            operation=operation_name,
            git_repository_id=repository_id,
            message=str(exc),
        )

    import service_factory

    git_service = service_factory.build_git_service()

    try:
        result = await asyncio.to_thread(
            operation,
            git_service,
            repository,
            config,
            context,
        )
    except Exception as exc:
        logger.error(
            "%s failed run_id=%s repository_id=%s: %s", step_id, context.run_id, repository_id, exc
        )
        return _failure_outcomes(
            context=context,
            node_id=node_id,
            step_id=step_id,
            operation=operation_name,
            git_repository_id=repository_id,
            message=str(exc),
        )

    metadata = {
        **context.metadata,
        _metadata_key(node_id): result,
    }
    logger.info(
        "%s succeeded run_id=%s repository_id=%s operation=%s",
        step_id,
        context.run_id,
        repository_id,
        operation_name,
    )
    return [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"metadata": metadata}),
        )
    ]
