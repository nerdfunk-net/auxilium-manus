from __future__ import annotations

import uuid as uuid_mod
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models.background_tier import WorkflowBackgroundTier


class BackgroundTierRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_workflow_id(self, workflow_id: int) -> WorkflowBackgroundTier | None:
        stmt = select(WorkflowBackgroundTier).where(
            WorkflowBackgroundTier.workflow_id == workflow_id
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_all(self) -> list[WorkflowBackgroundTier]:
        stmt = select(WorkflowBackgroundTier)
        return list(self.db.execute(stmt).scalars())

    def fingerprint(self) -> tuple[int, datetime | None]:
        """Cheap change signal for the dynamic worker's poll loop — a count +
        max(updated_at) over this tiny table, not a manually-bumped version
        counter, so there's no separate source of truth to keep in sync."""
        stmt = select(func.count(), func.max(WorkflowBackgroundTier.updated_at))
        count, max_updated_at = self.db.execute(stmt).one()
        return (count, max_updated_at)

    def publish(
        self,
        workflow_id: int,
        *,
        concurrency_limit: int | None,
        published_by_id: int | None,
    ) -> WorkflowBackgroundTier:
        row = self.get_by_workflow_id(workflow_id)
        if row is not None:
            row.concurrency_limit = concurrency_limit
            self.db.commit()
            self.db.refresh(row)
            return row

        row = WorkflowBackgroundTier(
            uuid=str(uuid_mod.uuid4()),
            workflow_id=workflow_id,
            hatchet_workflow_name=f"WorkflowBackground-{workflow_id}",
            concurrency_limit=concurrency_limit,
            published_by_id=published_by_id,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def unpublish(self, row: WorkflowBackgroundTier) -> None:
        self.db.delete(row)
        self.db.commit()
