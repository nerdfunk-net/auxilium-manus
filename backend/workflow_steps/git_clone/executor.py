"""Executor for the git-clone step."""

from __future__ import annotations

from typing import Any

from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from workflow_steps.common.git_workflow_step import run_git_workflow_step


def _clone_operation(
    git_service: Any,
    repository: dict[str, Any],
    config: dict[str, Any],
    context: WorkflowContext,
) -> dict[str, Any]:
    del config, context
    repo_path = git_service.get_repo_path(repository)
    git_service.clone(repository)
    return {
        "success": True,
        "operation": "clone",
        "git_source_id": repository.get("source_id") or repository.get("name"),
        "path": str(repo_path),
        "branch": repository.get("branch", "main"),
        "message": "Repository cloned successfully",
    }


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
) -> list[StepOutcome]:
    return await run_git_workflow_step(
        config=config,
        context=context,
        run=run,
        artifact_service=artifact_service,
        node_id=node_id,
        step_id="git-clone",
        operation=_clone_operation,
        operation_name="clone",
    )
