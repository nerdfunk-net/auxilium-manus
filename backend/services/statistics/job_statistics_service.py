from __future__ import annotations

from sqlalchemy.orm import Session

from core.domain_exceptions import AccessDeniedError, NotFoundError
from models.job_statistics import (
    JobStatisticsPieResponse,
    JobStatisticsSummaryItem,
    JobStatisticsSummaryListResponse,
)
from repositories.job_statistics_repository import JobStatisticsRepository
from repositories.workflow_repository import WorkflowRepository


class JobStatisticsService:
    def __init__(self, db: Session) -> None:
        self._repo = JobStatisticsRepository(db)
        self._workflow_repo = WorkflowRepository(db)

    def list_jobs_with_stats(self, user_id: int) -> JobStatisticsSummaryListResponse:
        workflows = self._repo.list_workflow_ids_with_stats(user_id)
        items: list[JobStatisticsSummaryItem] = []
        for workflow_id, workflow_name, workflow_visibility in workflows:
            latest_run_id = self._repo.get_latest_run_id(workflow_id)
            if latest_run_id is None:
                continue
            success_count, failed_count = self._repo.get_run_counts(latest_run_id)
            run_created_at = self._repo.get_run_created_at(latest_run_id)
            if run_created_at is None:
                continue
            items.append(
                JobStatisticsSummaryItem(
                    workflow_id=workflow_id,
                    workflow_name=workflow_name,
                    workflow_visibility=workflow_visibility,
                    latest_run_id=latest_run_id,
                    latest_run_created_at=run_created_at,
                    success_count=success_count,
                    failed_count=failed_count,
                    total_count=success_count + failed_count,
                )
            )
        return JobStatisticsSummaryListResponse(jobs=items)

    def get_pie_data(self, user_id: int, workflow_id: int) -> JobStatisticsPieResponse:
        result = self._workflow_repo.get_by_id(workflow_id)
        if result is None:
            raise NotFoundError("Workflow not found")
        workflow, _creator_username = result
        if workflow.visibility == "private" and workflow.creator_id != user_id:
            raise AccessDeniedError("Access denied")

        latest_run_id = self._repo.get_latest_run_id(workflow_id)
        if latest_run_id is None:
            raise NotFoundError("No recorded statistics for this workflow yet")

        success_count, failed_count = self._repo.get_run_counts(latest_run_id)
        run_created_at = self._repo.get_run_created_at(latest_run_id)
        if run_created_at is None:
            raise NotFoundError("No recorded statistics for this workflow yet")

        return JobStatisticsPieResponse(
            workflow_id=workflow.id,
            workflow_name=workflow.name,
            run_id=latest_run_id,
            run_created_at=run_created_at,
            success_count=success_count,
            failed_count=failed_count,
            total_count=success_count + failed_count,
        )
