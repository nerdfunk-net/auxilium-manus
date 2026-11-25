from __future__ import annotations

from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from core.models.notifications import Notification
from core.models.workflows import Workflow


class NotificationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def replace_for_node(
        self, *, run_id: int, node_id: str, rows: list[dict[str, Any]]
    ) -> list[Notification]:
        """Idempotent per (run, node, device): the earlier rows of the devices in ``rows`` (and the
        device-less "left out" row) are replaced in one transaction, so a Hatchet retry or a re-run
        of the node does not double them. Rows of other devices of the same node (fan-out
        children) are left alone. A failed write is rolled back, never left on the run session."""
        names = [row["device_name"] for row in rows if row["device_name"] is not None]
        clauses = [Notification.device_name.in_(names)] if names else []
        if any(row["device_name"] is None for row in rows):
            clauses.append(Notification.device_name.is_(None))
        try:
            if clauses:
                self.db.execute(
                    delete(Notification).where(
                        Notification.run_id == run_id,
                        Notification.node_id == node_id,
                        or_(*clauses),
                    )
                )
            notifications = [Notification(**row) for row in rows]
            self.db.add_all(notifications)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
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
