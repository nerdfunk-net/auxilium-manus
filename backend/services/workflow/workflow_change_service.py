"""DB-backed audit trail for workflow saves — the "Changes" tab of the workflow wiki.

Independent of Git-backed versioning: an entry is recorded on every save via
``record_change`` regardless of ``Workflow.is_version_controlled``. When the
save also produced a successful git commit (see WorkflowGitService), the
commit sha is attached so the UI can offer a diff for that entry, reusing the
existing git diff endpoint/viewer — no separate diff computation here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast

from models.workflow_changes import (
    WorkflowChangeAction,
    WorkflowChangeListResponse,
    WorkflowChangeResponse,
)
from repositories.workflow_change_repository import WorkflowChangeRepository

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from core.models.workflow_changes import WorkflowChange
    from services.workflow.workflow_git_service import WorkflowGitSyncResult


def _to_response(change: WorkflowChange) -> WorkflowChangeResponse:
    return WorkflowChangeResponse(
        id=change.id,
        actor_id=change.actor_id,
        actor_username=change.actor_username,
        action=cast(WorkflowChangeAction, change.action),
        commit_sha=change.commit_sha,
        parent_commit_sha=change.parent_commit_sha,
        has_diff=bool(change.commit_sha and change.parent_commit_sha),
        created_at=change.created_at,
    )


class WorkflowChangeService:
    def __init__(self, db: Session) -> None:
        self.repo = WorkflowChangeRepository(db)

    def record_change(
        self,
        workflow_id: int,
        *,
        action: Literal["created", "updated"],
        actor_id: int | None,
        actor_username: str | None,
        git_result: WorkflowGitSyncResult | None,
    ) -> WorkflowChange:
        commit_sha = git_result.commit_sha if git_result and git_result.status == "ok" else None
        parent_commit_sha = self.repo.get_latest_commit_sha(workflow_id) if commit_sha else None
        return self.repo.create(
            workflow_id=workflow_id,
            actor_id=actor_id,
            actor_username=actor_username,
            action=action,
            commit_sha=commit_sha,
            parent_commit_sha=parent_commit_sha,
        )

    def list_changes(self, workflow_id: int) -> WorkflowChangeListResponse:
        changes = self.repo.list_by_workflow(workflow_id)
        return WorkflowChangeListResponse(changes=[_to_response(c) for c in changes])
