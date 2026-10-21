from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.models.users import User
from core.rate_limit import rate_limited
from models.schedules import (
    ScheduleRunNowResponse,
    WorkflowScheduleCreate,
    WorkflowScheduleResponse,
    WorkflowScheduleUpdate,
)
from routers.workflow_steps import get_plugin_service
from services.execution.schedule_service import ScheduleService
from services.plugin_registry.plugin_registry_service import PluginRegistryService

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
def list_schedules(
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
def create_schedule(
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
def get_schedule(
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
def update_schedule(
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
def delete_schedule(
    schedule_id: int,
    current_user: User = Depends(get_current_user),
    service: ScheduleService = Depends(_service),
) -> None:
    service.delete_schedule(schedule_id=schedule_id, user_id=current_user.id)


@router.post(
    "/schedules/{schedule_id}/run",
    response_model=ScheduleRunNowResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(require_permission("workflows", "execute")),
        # Starts a real run (device fan-out), so it gets its own per-user budget.
        Depends(rate_limited("schedule-run-now", attempts=10, window_seconds=60)),
    ],
)
def run_schedule_now(
    schedule_id: int,
    current_user: User = Depends(get_current_user),
    service: ScheduleService = Depends(_service),
    plugin_service: PluginRegistryService = Depends(get_plugin_service),
) -> ScheduleRunNowResponse:
    return service.run_now(
        schedule_id=schedule_id,
        user_id=current_user.id,
        plugin_registry_service=plugin_service,
    )
