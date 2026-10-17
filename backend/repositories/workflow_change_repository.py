from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models.workflow_changes import WorkflowChange


class WorkflowChangeRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        *,
        workflow_id: int,
        actor_id: int | None,
        actor_username: str | None,
        action: str,
        commit_sha: str | None,
        parent_commit_sha: str | None,
    ) -> WorkflowChange:
        change = WorkflowChange(
            workflow_id=workflow_id,
            actor_id=actor_id,
            actor_username=actor_username,
            action=action,
            commit_sha=commit_sha,
            parent_commit_sha=parent_commit_sha,
        )
        self.db.add(change)
        self.db.commit()
        self.db.refresh(change)
        return change

    def list_by_workflow(self, workflow_id: int, limit: int = 100) -> list[WorkflowChange]:
        stmt = (
            select(WorkflowChange)
            .where(WorkflowChange.workflow_id == workflow_id)
            .order_by(WorkflowChange.created_at.desc(), WorkflowChange.id.desc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars())

    def get_latest_commit_sha(self, workflow_id: int) -> str | None:
        stmt = (
            select(WorkflowChange.commit_sha)
            .where(
                WorkflowChange.workflow_id == workflow_id,
                WorkflowChange.commit_sha.is_not(None),
            )
            .order_by(WorkflowChange.created_at.desc(), WorkflowChange.id.desc())
            .limit(1)
        )
        row = self.db.execute(stmt).first()
        return row[0] if row else None
