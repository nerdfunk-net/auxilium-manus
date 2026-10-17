from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.models.users import User
from models.background_tier import BackgroundTierResponse, BackgroundTierUpsert
from services.execution.background_tier_service import BackgroundTierService

router = APIRouter(
    tags=["workflow-background-tier"],
    dependencies=[Depends(get_current_user)],
)


def _service(db: Session = Depends(get_db)) -> BackgroundTierService:
    return BackgroundTierService(db)


@router.get(
    "/workflows/{workflow_id}/background-tier",
    response_model=BackgroundTierResponse | None,
    dependencies=[Depends(require_permission("workflows", "publish"))],
)
def get_background_tier(
    workflow_id: int,
    current_user: User = Depends(get_current_user),
    service: BackgroundTierService = Depends(_service),
) -> BackgroundTierResponse | None:
    return service.get_status(workflow_id=workflow_id, user_id=current_user.id)


@router.put(
    "/workflows/{workflow_id}/background-tier",
    response_model=BackgroundTierResponse,
    dependencies=[Depends(require_permission("workflows", "publish"))],
)
def publish_workflow(
    workflow_id: int,
    body: BackgroundTierUpsert,
    current_user: User = Depends(get_current_user),
    service: BackgroundTierService = Depends(_service),
) -> BackgroundTierResponse:
    return service.publish(workflow_id=workflow_id, data=body, user_id=current_user.id)


@router.get(
    "/workflows/{workflow_id}/background-tier/has-active-runs",
    response_model=bool,
    dependencies=[Depends(require_permission("workflows", "publish"))],
)
def has_active_runs(
    workflow_id: int,
    service: BackgroundTierService = Depends(_service),
) -> bool:
    return service.has_active_runs(workflow_id)


@router.delete(
    "/workflows/{workflow_id}/background-tier",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("workflows", "publish"))],
)
def unpublish_workflow(
    workflow_id: int,
    current_user: User = Depends(get_current_user),
    service: BackgroundTierService = Depends(_service),
) -> None:
    service.unpublish(workflow_id=workflow_id, user_id=current_user.id)
