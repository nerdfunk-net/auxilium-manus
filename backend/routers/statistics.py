from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.models.users import User
from models.job_statistics import JobStatisticsPieResponse, JobStatisticsSummaryListResponse
from services.statistics.job_statistics_service import JobStatisticsService

router = APIRouter(
    prefix="/statistics",
    tags=["statistics"],
    dependencies=[Depends(get_current_user)],
)


def _service(db: Session = Depends(get_db)) -> JobStatisticsService:
    return JobStatisticsService(db)


@router.get(
    "/jobs",
    response_model=JobStatisticsSummaryListResponse,
    dependencies=[Depends(require_permission("workflow_runs", "read"))],
)
def list_jobs_with_stats(
    current_user: User = Depends(get_current_user),
    service: JobStatisticsService = Depends(_service),
) -> JobStatisticsSummaryListResponse:
    return service.list_jobs_with_stats(current_user.id)


@router.get(
    "/jobs/{workflow_id}/pie",
    response_model=JobStatisticsPieResponse,
    dependencies=[Depends(require_permission("workflow_runs", "read"))],
)
def get_job_pie_data(
    workflow_id: int,
    current_user: User = Depends(get_current_user),
    service: JobStatisticsService = Depends(_service),
) -> JobStatisticsPieResponse:
    return service.get_pie_data(current_user.id, workflow_id)
