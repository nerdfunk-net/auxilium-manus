from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.models.users import User
from models.dashboard import (
    DashboardNotificationListResponse,
    DashboardRecentRunsResponse,
    DashboardScheduleListResponse,
)
from models.user_preferences import DashboardLayoutResponse, DashboardLayoutUpdate
from services.dashboard.dashboard_service import DashboardService
from services.users.user_preference_service import UserPreferenceService

router = APIRouter(
    prefix="/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(get_current_user)],
)


def _preference_service(db: Session = Depends(get_db)) -> UserPreferenceService:
    return UserPreferenceService(db)


def _dashboard_service(db: Session = Depends(get_db)) -> DashboardService:
    return DashboardService(db)


@router.get("/layout", response_model=DashboardLayoutResponse)
async def get_dashboard_layout(
    current_user: User = Depends(get_current_user),
    service: UserPreferenceService = Depends(_preference_service),
) -> DashboardLayoutResponse:
    return service.get_dashboard_layout(current_user.id)


@router.put("/layout", response_model=DashboardLayoutResponse)
async def update_dashboard_layout(
    body: DashboardLayoutUpdate,
    current_user: User = Depends(get_current_user),
    service: UserPreferenceService = Depends(_preference_service),
) -> DashboardLayoutResponse:
    return service.update_dashboard_layout(current_user.id, body)


@router.get(
    "/schedules",
    response_model=DashboardScheduleListResponse,
    dependencies=[Depends(require_permission("workflows", "read"))],
)
async def get_dashboard_schedules(
    current_user: User = Depends(get_current_user),
    service: DashboardService = Depends(_dashboard_service),
) -> DashboardScheduleListResponse:
    return service.list_schedules(current_user.id)


@router.get(
    "/recent-runs",
    response_model=DashboardRecentRunsResponse,
    dependencies=[Depends(require_permission("workflow_runs", "read"))],
)
async def get_dashboard_recent_runs(
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    service: DashboardService = Depends(_dashboard_service),
) -> DashboardRecentRunsResponse:
    return service.list_recent_runs(current_user.id, limit=limit)


@router.get(
    "/notifications",
    response_model=DashboardNotificationListResponse,
    dependencies=[Depends(require_permission("workflow_runs", "read"))],
)
async def get_dashboard_notifications(
    limit: int = Query(10, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    service: DashboardService = Depends(_dashboard_service),
) -> DashboardNotificationListResponse:
    return service.list_notifications(current_user.id, limit=limit)
