from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from core.models.job_statistics import JobStatistic
from core.models.workflows import Workflow


class JobStatisticsRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_batch(self, rows: list[dict[str, Any]]) -> list[JobStatistic]:
        stats = [JobStatistic(**row) for row in rows]
        self.db.add_all(stats)
        self.db.commit()
        for stat in stats:
            self.db.refresh(stat)
        return stats

    def list_workflow_ids_with_stats(self, user_id: int) -> list[tuple[int, str, str]]:
        """Distinct (workflow_id, name, visibility) for workflows visible to
        user_id that have at least one recorded statistic. Name/visibility come
        from the live Workflow row (not the denormalized snapshot on
        JobStatistic), since a workflow with any job_statistics rows still
        exists — job_statistics cascades away with its owning workflow via
        workflow_runs."""
        stmt = (
            select(Workflow.id, Workflow.name, Workflow.visibility)
            .join(JobStatistic, JobStatistic.workflow_id == Workflow.id)
            .where(or_(Workflow.visibility == "public", Workflow.creator_id == user_id))
            .distinct()
            .order_by(Workflow.name)
        )
        return [(row.id, row.name, row.visibility) for row in self.db.execute(stmt)]

    def get_latest_run_id(self, workflow_id: int) -> int | None:
        stmt = select(func.max(JobStatistic.run_id)).where(JobStatistic.workflow_id == workflow_id)
        return self.db.scalar(stmt)

    def get_run_counts(self, run_id: int) -> tuple[int, int]:
        stmt = (
            select(JobStatistic.result, func.count())
            .where(JobStatistic.run_id == run_id)
            .group_by(JobStatistic.result)
        )
        counts = {result: count for result, count in self.db.execute(stmt)}
        return counts.get("success", 0), counts.get("failed", 0)

    def get_run_created_at(self, run_id: int) -> datetime | None:
        stmt = select(func.min(JobStatistic.created_at)).where(JobStatistic.run_id == run_id)
        return self.db.scalar(stmt)
