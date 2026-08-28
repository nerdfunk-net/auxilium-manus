"""Executor for the git-pull step."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from workflow_steps.common.git_workflow_step import run_git_workflow_step

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool


def _pull_operation(
    git_service: Any,
    repository: dict[str, Any],
    config: dict[str, Any],
    context: WorkflowContext,
) -> dict[str, Any]:
    del config, context
    result = git_service.pull(repository)
    if not result.success:
        raise RuntimeError(result.message)
    repo_path = git_service.get_repo_path(repository)
    return {
        "success": True,
        "operation": "pull",
        "git_repository_id": repository.get("id"),
        "path": str(repo_path),
        "branch": result.branch or repository.get("branch", "main"),
        "commits_pulled": result.commits_pulled,
        "message": result.message,
    }


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    return await run_git_workflow_step(
        config=config,
        context=context,
        run=run,
        artifact_service=artifact_service,
        node_id=node_id,
        step_id="git-pull",
        operation=_pull_operation,
        operation_name="pull",
    )
