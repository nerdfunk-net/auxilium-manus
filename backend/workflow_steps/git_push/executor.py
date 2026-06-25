"""Executor for the git-push step."""

from __future__ import annotations

from typing import Any

from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from workflow_steps.common.device_template import render_step_template
from workflow_steps.common.git_push_helpers import (
    collect_export_paths_for_commit,
    parse_commit_before_push,
)
from workflow_steps.common.git_workflow_step import run_git_workflow_step
from workflow_steps.git_push.config import get_config


def _commit_message(config: dict[str, Any], context: WorkflowContext) -> str:
    template = str(
        config.get("commit_message_template")
        or get_config().get("commit_message_template")
        or "commit {timestamp}"
    ).strip()
    return render_step_template(
        template,
        run_id=context.run_id,
        workflow_id=context.workflow_id,
    )


def _push_operation(
    git_service: Any,
    repository: dict[str, Any],
    config: dict[str, Any],
    context: WorkflowContext,
) -> dict[str, Any]:
    repo = git_service.open_or_clone(repository)
    repo_path = git_service.get_repo_path(repository)

    commit_sha: str | None = None
    files_changed = 0
    committed = False

    if parse_commit_before_push(config):
        export_paths = collect_export_paths_for_commit(context, repo_root=repo_path)
        if export_paths:
            commit_result = git_service.commit(
                repository,
                message=_commit_message(config, context),
                files=export_paths,
                repo=repo,
            )
        else:
            commit_result = git_service.commit(
                repository,
                message=_commit_message(config, context),
                repo=repo,
                add_all=True,
            )
        if not commit_result.success:
            raise RuntimeError(commit_result.message)
        commit_sha = commit_result.commit_sha
        files_changed = commit_result.files_changed
        committed = files_changed > 0

    push_result = git_service.push(repository, repo=repo)
    if not push_result.success:
        raise RuntimeError(push_result.message)

    return {
        "success": True,
        "operation": "push",
        "git_source_id": repository.get("source_id") or repository.get("name"),
        "path": str(repo_path),
        "branch": push_result.branch or repository.get("branch", "main"),
        "committed": committed,
        "commit_sha": commit_sha,
        "files_changed": files_changed,
        "pushed": push_result.pushed,
        "message": push_result.message,
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
        step_id="git-push",
        operation=_push_operation,
        operation_name="push",
    )
