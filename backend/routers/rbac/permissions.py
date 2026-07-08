from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.safe_http_errors import raise_internal_server_error
from models.rbac import Permission, PermissionCreate
from services.auth.rbac_service import RBACService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/rbac/permissions",
    tags=["rbac"],
    dependencies=[Depends(get_current_user)],
)


def _service(db: Session = Depends(get_db)) -> RBACService:
    return RBACService(db)


@router.get(
    "",
    response_model=list[Permission],
    dependencies=[Depends(require_permission("rbac.permissions", "read"))],
)
async def list_permissions(service: RBACService = Depends(_service)) -> list[Permission]:
    return [Permission.model_validate(p) for p in service.list_permissions()]


@router.post(
    "",
    response_model=Permission,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("rbac.permissions", "write"))],
)
async def create_permission(
    payload: PermissionCreate,
    service: RBACService = Depends(_service),
) -> Permission:
    try:
        permission = service.create_permission(
            payload.resource,
            payload.action,
            payload.description,
        )
        return Permission.model_validate(permission)
    except Exception as exc:  # noqa: BLE001
        raise_internal_server_error(logger, "Failed to create permission", exc)


@router.get(
    "/{permission_id}",
    response_model=Permission,
    dependencies=[Depends(require_permission("rbac.permissions", "read"))],
)
async def get_permission(
    permission_id: int,
    service: RBACService = Depends(_service),
) -> Permission:
    permission = service.get_permission_by_id(permission_id)
    if permission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found")
    return Permission.model_validate(permission)


@router.delete(
    "/{permission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("rbac.permissions", "delete"))],
)
async def delete_permission(permission_id: int, service: RBACService = Depends(_service)) -> None:
    deleted = service.delete_permission(permission_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found")
