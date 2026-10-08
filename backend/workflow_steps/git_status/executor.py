"""Executor for the git-status step (read-only working-tree / origin-sync check)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.git.working_tree_status import collect_status
from workflow_steps.common.git_workflow_step import parse_bool, run_git_workflow_step

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

_CLEAN = "clean"
_DIRTY = "dirty"


def _flag(config: dict[str, Any], key: str, default: bool) -> bool:
    return default if key not in config else parse_bool(config[key])


_CHECK_PHRASES = (
    ("uncommitted", "no uncommitted changes"),
    ("untracked", "no untracked files"),
    ("sync", "in sync with origin"),
)


def _summarize(status: dict[str, Any]) -> str:
    """Describe only what the enabled checks looked at / found."""
    if status["clean"]:
        checked = [text for key, text in _CHECK_PHRASES if status["checks"][key]]
        return f"clean: {', '.join(checked)}" if checked else "clean: all checks disabled"
    reasons = status["reasons"]
    parts: list[str] = []
    if "uncommitted_changes" in reasons:
        parts.extend(
            f"{status[key]} {label}"
            for key, label in (("modified_count", "modified"), ("staged_count", "staged"))
            if status[key]
        )
    if "untracked_files" in reasons:
        parts.append(f"{status['untracked_count']} untracked")
    if "ahead_of_origin" in reasons:
        parts.append(f"{status['ahead_count']} ahead")
    if "behind_origin" in reasons:
        parts.append(f"{status['behind_count']} behind")
    parts.extend(r for r in reasons if r in ("branch_mismatch", "no_remote_branch"))
    return "dirty: " + ", ".join(parts)


def _result_outcome(result: dict[str, Any]) -> tuple[str, str]:
    return (_CLEAN if result["clean"] else _DIRTY), _summarize(result)


def _status_operation(
    git_service: Any,
    repository: dict[str, Any],
    config: dict[str, Any],
    context: WorkflowContext,
) -> dict[str, Any]:
    del context
    status = collect_status(
        git_service,
        repository,
        fetch=_flag(config, "fetch_remote", True),
        check_uncommitted=_flag(config, "check_uncommitted", True),
        check_untracked=_flag(config, "check_untracked", True),
        check_sync=_flag(config, "check_sync", True),
    )
    return {
        "success": True,
        "operation": "status",
        "git_repository_id": repository.get("id"),
        "path": str(git_service.get_repo_path(repository)),
        **status,
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
        step_id="git-status",
        operation=_status_operation,
        operation_name="status",
        result_outcome=_result_outcome,
        result_outcome_names=(_CLEAN, _DIRTY),
    )
