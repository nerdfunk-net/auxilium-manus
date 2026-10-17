from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from core.models.notifications import Notification
from core.models.workflows import Workflow


class NotificationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_batch(self, rows: list[dict[str, Any]]) -> list[Notification]:
        notifications = [Notification(**row) for row in rows]
        self.db.add_all(notifications)
        self.db.commit()
        for notification in notifications:
            self.db.refresh(notification)
        return notifications

    def list_recent(self, user_id: int, *, limit: int) -> list[Notification]:
        stmt = (
            select(Notification)
            .join(Workflow, Notification.workflow_id == Workflow.id)
            .where(or_(Workflow.visibility == "public", Workflow.creator_id == user_id))
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt))
