"""Git-backed version control for workflow definitions.

Best-effort: writes, commits, and pushes a workflow's canonical JSON into the
single configured ``category="workflows"`` GitRepository. This never raises
out of ``sync_workflow_to_git`` — Git is a backup/history layer here, not a
transactional partner for the DB save, which has already committed by the
time this runs. See doc/WORKFLOW-STEPS.md-adjacent pattern in
services/artifacts/sinks/git_sink.py for the same write-then-commit-then-push
shape this mirrors.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from core.domain_exceptions import NotFoundError, ValidationFailedError
from models.git_repositories import GitCategory
from models.workflows import WorkflowUpdate
from services.git.repository_service import GitRepositoryService
from services.git.shared_utils import get_git_repo_by_id
from services.workflow_context.device_template import sanitize_relative_path

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from core.models.workflows import Workflow

logger = logging.getLogger(__name__)

_GIT_ACTION_VERBS = {"create": "Create", "update": "Update", "restore": "Restore"}


@dataclass(frozen=True)
class WorkflowGitSyncResult:
    """Outcome of a best-effort Git sync attempt."""

    status: Literal["ok", "failed", "skipped"]
    commit_sha: str | None = None
    pushed: bool = False
    message: str | None = None


def _workflow_git_path(workflow_uuid: str) -> str:
    return sanitize_relative_path(f"workflows/{workflow_uuid}.json")


def _workflow_to_git_payload(workflow: Workflow) -> dict[str, Any]:
    """Content-only view of a workflow.

    Excludes DB-only bookkeeping (id, creator_id, timestamps) so that saves
    with no real content change don't produce noisy diffs in git history.
    """
    return {
        "uuid": workflow.uuid,
        "name": workflow.name,
        "description": workflow.description,
        "folder": workflow.folder,
        "visibility": workflow.visibility,
        "canvas_nodes": workflow.canvas_nodes,
        "canvas_edges": workflow.canvas_edges,
        "canvas_groups": workflow.canvas_groups,
        "static_attributes": workflow.static_attributes,
    }


class WorkflowGitService:
    """Wraps the shared Git subsystem for workflow-definition version control."""

    def __init__(self, db: Session) -> None:
        self._repos = GitRepositoryService(db)

        import service_factory

        self._git = service_factory.build_git_service()
        self._files = service_factory.build_git_file_service()
        self._vc = service_factory.build_git_version_control_service()

    def get_configured_repository(self) -> dict[str, Any] | None:
        """The single active ``category="workflows"`` repository, or None."""
        repos = self._repos.get_repositories(category=GitCategory.WORKFLOWS, active_only=True)
        return repos[0] if repos else None

    def sync_workflow_to_git(
        self,
        workflow: Workflow,
        *,
        action: Literal["create", "update", "restore"],
        actor_username: str | None = None,
    ) -> WorkflowGitSyncResult:
        """Write, commit, and push the workflow's definition. Never raises."""
        if not workflow.is_version_controlled:
            return WorkflowGitSyncResult(
                status="skipped", message="Workflow is not version controlled"
            )
        if not workflow.uuid:
            return WorkflowGitSyncResult(status="skipped", message="Workflow has no uuid")

        repository = self.get_configured_repository()
        if repository is None:
            return WorkflowGitSyncResult(
                status="skipped", message="No workflow Git repository configured"
            )

        try:
            return self._sync(workflow, repository, action=action, actor_username=actor_username)
        except Exception as exc:  # noqa: BLE001 - best-effort sync must never propagate
            logger.warning(
                "Git sync failed for workflow id=%s uuid=%s action=%s: %s",
                workflow.id,
                workflow.uuid,
                action,
                exc,
                exc_info=True,
            )
            return WorkflowGitSyncResult(status="failed", message=str(exc))

    def _sync(
        self,
        workflow: Workflow,
        repository: dict[str, Any],
        *,
        action: Literal["create", "update", "restore"],
        actor_username: str | None,
    ) -> WorkflowGitSyncResult:
        relative_path = _workflow_git_path(workflow.uuid)
        repo = self._git.open_or_clone(repository)

        payload = _workflow_to_git_payload(workflow)
        content = json.dumps(payload, indent=2, sort_keys=True) + "\n"

        target = self._git.get_repo_path(repository) / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

        verb = _GIT_ACTION_VERBS[action]
        message = f"{verb}: workflow '{workflow.name}' ({workflow.uuid})"
        if actor_username:
            message = f"{message} by {actor_username}"

        commit_result = self._git.commit(
            repository, message=message, files=[relative_path], repo=repo
        )
        if not commit_result.success:
            return WorkflowGitSyncResult(status="failed", message=commit_result.message)

        if commit_result.files_changed == 0:
            return WorkflowGitSyncResult(status="ok", message="No changes to commit")

        push_result = self._git.push(repository, repo=repo)
        if not push_result.success:
            return WorkflowGitSyncResult(
                status="failed",
                commit_sha=commit_result.commit_sha,
                pushed=False,
                message=f"Committed locally but push failed: {push_result.message}",
            )

        return WorkflowGitSyncResult(
            status="ok",
            commit_sha=commit_result.commit_sha,
            pushed=push_result.pushed,
            message=commit_result.message,
        )

    def get_history(self, workflow: Workflow) -> dict[str, Any]:
        """Full commit history for this workflow's file."""
        repository = self._require_repository(workflow)
        relative_path = _workflow_git_path(workflow.uuid)
        history = self._files.get_file_history(repository["id"], relative_path)
        return {**history, "repository_name": repository["name"]}

    def get_diff(self, workflow: Workflow, commit_a: str, commit_b: str) -> dict[str, Any]:
        """Unified + side-by-side diff of this workflow's file between two commits."""
        repository = self._require_repository(workflow)
        relative_path = _workflow_git_path(workflow.uuid)
        return self._vc.compare_commits(repository["id"], commit_a, commit_b, relative_path)

    def restore_version(self, workflow: Workflow, commit_sha: str) -> WorkflowUpdate:
        """Build a WorkflowUpdate from this workflow's file content at commit_sha.

        Does not touch the DB itself — the caller applies the result through
        the normal WorkflowService.update_workflow(...) path, which
        re-validates and re-syncs, producing a new forward commit. Restore
        never runs git reset/revert or rewrites history.
        """
        repository = self._require_repository(workflow)
        relative_path = _workflow_git_path(workflow.uuid)
        repo = get_git_repo_by_id(repository["id"], self._repos)

        try:
            commit = repo.commit(commit_sha)
            raw = (commit.tree / relative_path).data_stream.read().decode("utf-8")
        except KeyError:
            raise NotFoundError(
                f"File '{relative_path}' not found at commit {commit_sha[:8]}"
            ) from None
        except Exception as exc:
            raise ValidationFailedError(f"Could not read commit {commit_sha!r}: {exc}") from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationFailedError(
                f"Workflow content at commit {commit_sha[:8]} is not valid JSON"
            ) from exc

        return WorkflowUpdate(
            name=data.get("name"),
            description=data.get("description"),
            folder=data.get("folder"),
            visibility=data.get("visibility"),
            canvas_nodes=data.get("canvas_nodes"),
            canvas_edges=data.get("canvas_edges"),
            canvas_groups=data.get("canvas_groups"),
            static_attributes=data.get("static_attributes"),
        )

    def _require_repository(self, workflow: Workflow) -> dict[str, Any]:
        if not workflow.is_version_controlled:
            raise ValidationFailedError("Workflow is not version controlled")
        repository = self.get_configured_repository()
        if repository is None:
            raise NotFoundError("No workflow Git repository configured")
        return repository
