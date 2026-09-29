from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models.runs import WorkflowRunEvent

# Per-run cap so a large fan-out against unreachable devices cannot bloat the table.
MAX_EVENTS_PER_RUN = 2000
MAX_MESSAGE_LENGTH = 1000
TRUNCATED_KIND = "truncated"


class RunEventRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add_event(
        self,
        *,
        run_id: int,
        step_node_id: str,
        kind: str,
        message: str,
        level: str = "info",
        device_name: str | None = None,
        child_index: int | None = None,
        max_events: int = MAX_EVENTS_PER_RUN,
    ) -> None:
        """Append one event, unless the run already holds ``max_events``.

        The event that hits the cap is replaced by a single ``truncated`` marker
        so readers can tell the log is incomplete; later events are dropped.
        """
        count = int(
            self.db.scalar(
                select(func.count())
                .select_from(WorkflowRunEvent)
                .where(WorkflowRunEvent.run_id == run_id)
            )
            or 0
        )
        if count > max_events:
            return
        if count == max_events:
            kind, level = TRUNCATED_KIND, "warning"
            message = f"Event log truncated after {max_events} events; later events are dropped."
            device_name, child_index = None, None
        self.db.add(
            WorkflowRunEvent(
                run_id=run_id,
                step_node_id=step_node_id,
                child_index=child_index,
                device_name=device_name,
                level=level,
                kind=kind,
                message=message[:MAX_MESSAGE_LENGTH],
            )
        )
        self.db.commit()

    def list_events(
        self, run_id: int, *, after_id: int = 0, limit: int = 500
    ) -> list[WorkflowRunEvent]:
        stmt = (
            select(WorkflowRunEvent)
            .where(WorkflowRunEvent.run_id == run_id, WorkflowRunEvent.id > after_id)
            .order_by(WorkflowRunEvent.id)
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars())
