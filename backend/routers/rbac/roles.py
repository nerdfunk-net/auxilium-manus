from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.safe_http_errors import raise_internal_server_error
from models.rbac import (
    Permission,
    PermissionWithGrant,
    Role,
    RoleCreate,
    RolePermissionAssignment,
    RoleUpdate,
    RoleWithPermissions,
)
from services.auth.rbac_service import RBACService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/rbac/roles",
    tags=["rbac"],
    dependencies=[Depends(get_current_user)],
)


def _service(db: Session = Depends(get_db)) -> RBACService:
    return RBACService(db)


def _to_role_with_permissions(service: RBACService, role) -> RoleWithPermissions:  # noqa: ANN001
    permissions = [
        PermissionWithGrant(
            **Permission.model_validate(p).model_dump(),
            granted=True,
            source="role",
        )
        for p in service.get_role_permissions(role.id)
    ]
    return RoleWithPermissions(**Role.model_validate(role).model_dump(), permissions=permissions)


@router.get(
    "",
    response_model=list[Role],
    dependencies=[Depends(require_permission("rbac.roles", "read"))],
)
async def list_roles(service: RBACService = Depends(_service)) -> list[Role]:
    return [Role.model_validate(r) for r in service.list_roles()]


@router.post(
    "",
    response_model=Role,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("rbac.roles", "write"))],
)
async def create_role(payload: RoleCreate, service: RBACService = Depends(_service)) -> Role:
    if service.role_name_exists(payload.name):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Role name already exists")

    try:
        role = service.create_role(payload.name, payload.description, payload.is_system)
        return Role.model_validate(role)
    except Exception as exc:  # noqa: BLE001
        raise_internal_server_error(logger, "Failed to create role", exc)


@router.get(
    "/{role_id}",
    response_model=RoleWithPermissions,
    dependencies=[Depends(require_permission("rbac.roles", "read"))],
)
async def get_role(role_id: int, service: RBACService = Depends(_service)) -> RoleWithPermissions:
    role = service.get_role(role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    return _to_role_with_permissions(service, role)


@router.put(
    "/{role_id}",
    response_model=Role,
    dependencies=[Depends(require_permission("rbac.roles", "write"))],
)
async def update_role(
    role_id: int,
    payload: RoleUpdate,
    service: RBACService = Depends(_service),
) -> Role:
    if payload.name is not None and service.role_name_exists(
        payload.name,
        exclude_role_id=role_id,
    ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Role name already exists")

    role = service.update_role(role_id, name=payload.name, description=payload.description)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    return Role.model_validate(role)


@router.delete(
    "/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("rbac.roles", "delete"))],
)
async def delete_role(role_id: int, service: RBACService = Depends(_service)) -> None:
    role = service.get_role(role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="System roles cannot be deleted",
        )

    service.delete_role(role_id)


@router.get(
    "/{role_id}/permissions",
    response_model=list[Permission],
    dependencies=[Depends(require_permission("rbac.roles", "read"))],
)
async def get_role_permissions(
    role_id: int,
    service: RBACService = Depends(_service),
) -> list[Permission]:
    if service.get_role(role_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    return [Permission.model_validate(p) for p in service.get_role_permissions(role_id)]


@router.post(
    "/{role_id}/permissions",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("rbac.roles", "write"))],
)
async def assign_role_permission(
    role_id: int,
    payload: RolePermissionAssignment,
    service: RBACService = Depends(_service),
) -> None:
    if service.get_role(role_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    if service.get_permission_by_id(payload.permission_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found")

    service.assign_permission_to_role(role_id, payload.permission_id, payload.granted)


@router.delete(
    "/{role_id}/permissions/{permission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("rbac.roles", "write"))],
)
async def remove_role_permission(
    role_id: int,
    permission_id: int,
    service: RBACService = Depends(_service),
) -> None:
    removed = service.remove_permission_from_role(role_id, permission_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role permission assignment not found",
        )
