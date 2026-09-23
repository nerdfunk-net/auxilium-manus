from __future__ import annotations

import uuid as uuid_mod
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models.workflow_ai_session import WorkflowAiSession


class WorkflowAiSessionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_active_for_workflow(self, workflow_id: int) -> WorkflowAiSession | None:
        stmt = (
            select(WorkflowAiSession)
            .where(
                WorkflowAiSession.workflow_id == workflow_id,
                WorkflowAiSession.expires_at > func.now(),
            )
            .order_by(WorkflowAiSession.created_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def create(
        self, workflow_id: int, *, enabled_by_id: int | None, expires_at: datetime
    ) -> WorkflowAiSession:
        row = WorkflowAiSession(
            uuid=str(uuid_mod.uuid4()),
            workflow_id=workflow_id,
            enabled_by_id=enabled_by_id,
            expires_at=expires_at,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def expire_active_for_workflow(self, workflow_id: int) -> None:
        # Must expire every currently-active row, not just the newest one
        # get_active_for_workflow would return — enable() never reuses an
        # existing row (it always inserts), so overlapping active rows are
        # possible (a second enable, two users, a retried PUT), and leaving
        # an older one valid would let ai_workflow_apply.py's own
        # get_active_for_workflow check keep succeeding after "disable".
        stmt = select(WorkflowAiSession).where(
            WorkflowAiSession.workflow_id == workflow_id,
            WorkflowAiSession.expires_at > func.now(),
        )
        rows = self.db.execute(stmt).scalars().all()
        if not rows:
            return
        for row in rows:
            row.expires_at = func.now()
        self.db.commit()
