"""Shared helpers for git workflow steps (clone, pull, push).

The actual git operation runs inside a per-repository advisory lock
(``services.git.repo_lock.git_repo_lock``) so two concurrent callers against
the same ``GitRepository`` — fan-out children, independent sibling branches,
or separate runs — never race on the shared working tree.
"""

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
from services.git.repo_lock import git_repo_lock
from services.git.scrub import scrub_url_credentials
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


# Maps an operation result to (outcome name, optional summary). Steps that route
# on more than success/failure (git-status: clean/dirty) pass one in.
ResultOutcome = Callable[[dict[str, Any]], tuple[str, str | None]]

_DEFAULT_SUCCESS_OUTCOME = "success"
_INACTIVE_MARKER_SUFFIX = ".branch_inactive"
_SKIPPED_MESSAGE = "Skipped: upstream routing step did not select this branch"

def _inactive_marker_key(node_id: str) -> str:
    return f"{node_id}{_INACTIVE_MARKER_SUFFIX}"


def _on_inactive_branch(context: WorkflowContext) -> bool:
    """True when no device reached this step AND an upstream routing step
    (git-status) marked this branch as not taken."""
    return not context.devices and any(
        key.endswith(_INACTIVE_MARKER_SUFFIX) and value is True
        for key, value in context.metadata.items()
    )


def _inactive_outcomes(
    *,
    context: WorkflowContext,
    node_id: str,
    metadata: dict[str, Any],
    names: tuple[str, ...],
) -> list[StepOutcome]:
    """The result outcomes a routing step did not take: no devices, plus a marker
    so downstream git steps know to stay a no-op instead of running on nothing."""
    inactive_metadata = {**metadata, _inactive_marker_key(node_id): True}
    return [
        StepOutcome(
            name=name,
            context=context.model_copy(update={"devices": {}, "metadata": inactive_metadata}),
        )
        for name in names
    ]


def _failure_outcomes(
    *,
    context: WorkflowContext,
    node_id: str,
    step_id: str,
    operation: str,
    git_repository_id: int | None,
    message: str,
    result_outcome_names: tuple[str, ...] = (),
) -> list[StepOutcome]:
    """Failure result. A routing step (``result_outcome_names`` = e.g. clean/dirty)
    emits every result outcome as inactive, so a failed check never reads as a
    verdict on the repository; other steps emit an empty ``success``."""
    message = scrub_url_credentials(message)
    metadata = {
        **context.metadata,
        _metadata_key(node_id): {
            "success": False,
            "operation": operation,
            "git_repository_id": git_repository_id,
            "message": message,
        },
    }
    if result_outcome_names:
        outcomes = _inactive_outcomes(
            context=context, node_id=node_id, metadata=metadata, names=result_outcome_names
        )
    else:
        outcomes = [
            StepOutcome(
                name=_DEFAULT_SUCCESS_OUTCOME,
                context=context.model_copy(update={"devices": {}, "metadata": metadata}),
            )
        ]
    if context.devices:
        failed_devices = _mark_devices_failed(
            devices=context.devices,
            node_id=node_id,
            step_id=step_id,
            message=message,
        )
        failure_update: dict[str, Any] = {"devices": failed_devices, "metadata": metadata}
    else:
        failure_update = {"metadata": metadata}
    outcomes.append(StepOutcome(name="failure", context=context.model_copy(update=failure_update)))
    return outcomes


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _skipped_outcomes(
    *, context: WorkflowContext, node_id: str, operation_name: str, repository_id: int
) -> list[StepOutcome]:
    """No-op outcome for a git step sitting on a branch an upstream router did not take."""
    return [
        StepOutcome(
            name=_DEFAULT_SUCCESS_OUTCOME,
            context=context.model_copy(
                update={
                    "metadata": {
                        **context.metadata,
                        _metadata_key(node_id): {
                            "success": True,
                            "skipped": True,
                            "operation": operation_name,
                            "git_repository_id": repository_id,
                            "message": _SKIPPED_MESSAGE,
                        },
                    }
                }
            ),
            summary=_SKIPPED_MESSAGE.lower(),
        )
    ]


def _apply_change_request_branch(
    repository: dict[str, Any],
    *,
    config: dict[str, Any],
    run: WorkflowRun,
    context: WorkflowContext,
    step_id: str,
) -> dict[str, Any]:
    """CI/CD pipeline: when this run deploys a change request and the step opted in,
    operate on the change request's per-change branch instead of the default branch."""
    if not parse_bool(config.get("use_change_request_branch")):
        return repository
    from workflow_steps.common.change_request_context import resolve_cr_ref

    cr_ref = resolve_cr_ref(run)
    if cr_ref is None:
        return repository
    branch, _commit = cr_ref
    logger.info(
        "%s targeting change-request branch %s run_id=%s", step_id, branch, context.run_id
    )
    return {**repository, "branch": branch}


def _success_outcomes(
    *,
    context: WorkflowContext,
    node_id: str,
    result: dict[str, Any],
    result_outcome: ResultOutcome | None,
    result_outcome_names: tuple[str, ...],
) -> list[StepOutcome]:
    metadata = {**context.metadata, _metadata_key(node_id): result}
    if result_outcome is None:
        return [
            StepOutcome(
                name=_DEFAULT_SUCCESS_OUTCOME,
                context=context.model_copy(update={"metadata": metadata}),
            )
        ]
    outcome_name, summary = result_outcome(result)
    taken = StepOutcome(
        name=outcome_name,
        context=context.model_copy(update={"metadata": metadata}),
        summary=summary,
    )
    untaken = _inactive_outcomes(
        context=context,
        node_id=node_id,
        metadata=metadata,
        names=tuple(name for name in result_outcome_names if name != outcome_name),
    )
    return [taken, *untaken]


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
    result_outcome: ResultOutcome | None = None,
    result_outcome_names: tuple[str, ...] = (),
) -> list[StepOutcome]:
    """Run one git operation under the per-repository lock.

    ``result_outcome`` / ``result_outcome_names`` are for routing steps
    (git-status: clean/dirty): the first maps the result to the taken outcome
    name and summary, the second lists every result outcome so the untaken ones
    are emitted as inactive. Every other git step becomes a no-op when it sits on
    such an inactive branch (no devices + marker) -- git-push must not commit
    and push just because the branch it hangs off was not selected.
    """
    del artifact_service

    repository_id = _git_repository_id(config)

    def _failure(message: str) -> list[StepOutcome]:
        return _failure_outcomes(
            context=context,
            node_id=node_id,
            step_id=step_id,
            operation=operation_name,
            git_repository_id=repository_id,
            message=message,
            result_outcome_names=result_outcome_names,
        )

    if repository_id is None:
        return _failure(f"{step_id}: git_repository_id is not configured")

    if result_outcome is None and _on_inactive_branch(context):
        logger.info(
            "%s skipped (inactive branch) run_id=%s repository_id=%s",
            step_id,
            context.run_id,
            repository_id,
        )
        return _skipped_outcomes(
            context=context,
            node_id=node_id,
            operation_name=operation_name,
            repository_id=repository_id,
        )

    logger.info("%s started run_id=%s repository_id=%s", step_id, context.run_id, repository_id)

    try:
        repository = load_git_repository(repository_id)
    except ValueError as exc:
        return _failure(str(exc))
    repository = _apply_change_request_branch(
        repository, config=config, run=run, context=context, step_id=step_id
    )

    import service_factory

    git_service = service_factory.build_git_service()

    def _run_locked() -> dict[str, Any]:
        # git_repo_lock does its own blocking wait (time.sleep polling) — run
        # the whole locked section in this thread, not on the event loop.
        with git_repo_lock(repository_id):
            return operation(git_service, repository, config, context)

    try:
        result = await asyncio.to_thread(_run_locked)
    except Exception as exc:
        logger.error(
            "%s failed run_id=%s repository_id=%s: %s",
            step_id,
            context.run_id,
            repository_id,
            scrub_url_credentials(str(exc)),
        )
        return _failure(str(exc))

    logger.info(
        "%s succeeded run_id=%s repository_id=%s operation=%s",
        step_id,
        context.run_id,
        repository_id,
        operation_name,
    )
    return _success_outcomes(
        context=context,
        node_id=node_id,
        result=result,
        result_outcome=result_outcome,
        result_outcome_names=result_outcome_names,
    )
