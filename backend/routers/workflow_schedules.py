from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.models.users import User
from models.schedules import (
    WorkflowScheduleCreate,
    WorkflowScheduleResponse,
    WorkflowScheduleUpdate,
)
from services.execution.schedule_service import ScheduleService

router = APIRouter(
    tags=["workflow-schedules"],
    dependencies=[Depends(get_current_user)],
)


def _service(db: Session = Depends(get_db)) -> ScheduleService:
    return ScheduleService(db)


@router.get(
    "/schedules",
    response_model=list[WorkflowScheduleResponse],
    dependencies=[Depends(require_permission("workflows", "execute"))],
)
async def list_schedules(
    workflow_id: int | None = None,
    current_user: User = Depends(get_current_user),
    service: ScheduleService = Depends(_service),
) -> list[WorkflowScheduleResponse]:
    return service.list_schedules(user_id=current_user.id, workflow_id=workflow_id)


@router.post(
    "/schedules",
    response_model=WorkflowScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(require_permission("workflows", "execute")),
        # Creating a schedule publishes the workflow to the background tier.
        Depends(require_permission("workflows", "publish")),
    ],
)
async def create_schedule(
    body: WorkflowScheduleCreate,
    current_user: User = Depends(get_current_user),
    service: ScheduleService = Depends(_service),
) -> WorkflowScheduleResponse:
    return service.create_schedule(data=body, user_id=current_user.id)


@router.get(
    "/schedules/{schedule_id}",
    response_model=WorkflowScheduleResponse,
    dependencies=[Depends(require_permission("workflows", "execute"))],
)
async def get_schedule(
    schedule_id: int,
    current_user: User = Depends(get_current_user),
    service: ScheduleService = Depends(_service),
) -> WorkflowScheduleResponse:
    return service.get_schedule(schedule_id=schedule_id, user_id=current_user.id)


@router.put(
    "/schedules/{schedule_id}",
    response_model=WorkflowScheduleResponse,
    dependencies=[Depends(require_permission("workflows", "execute"))],
)
async def update_schedule(
    schedule_id: int,
    body: WorkflowScheduleUpdate,
    current_user: User = Depends(get_current_user),
    service: ScheduleService = Depends(_service),
) -> WorkflowScheduleResponse:
    return service.update_schedule(
        schedule_id=schedule_id, data=body, user_id=current_user.id
    )


@router.delete(
    "/schedules/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("workflows", "execute"))],
)
async def delete_schedule(
    schedule_id: int,
    current_user: User = Depends(get_current_user),
    service: ScheduleService = Depends(_service),
) -> None:
    service.delete_schedule(schedule_id=schedule_id, user_id=current_user.id)
