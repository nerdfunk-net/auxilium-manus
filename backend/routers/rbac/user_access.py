from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.models.users import User
from models.rbac import (
    Permission,
    PermissionWithGrant,
    UserPermissionAssignment,
    UserPermissions,
    UserRoleAssignment,
)
from services.auth.rbac_service import RBACService
from services.users.user_service import UserService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/rbac/users",
    tags=["rbac"],
    dependencies=[Depends(get_current_user)],
)


def _service(db: Session = Depends(get_db)) -> RBACService:
    return RBACService(db)


def _build_user_permissions(service: RBACService, user_id: int) -> UserPermissions:
    permissions = [
        PermissionWithGrant(
            **Permission.model_validate(permission).model_dump(),
            granted=True,
            source=source,
        )
        for permission, source in service.get_effective_permissions(user_id)
    ]
    overrides = [
        PermissionWithGrant(
            **Permission.model_validate(permission).model_dump(),
            granted=granted,
            source="override",
        )
        for permission, granted in service.get_user_permission_overrides_with_status(user_id)
    ]

    return UserPermissions(
        user_id=user_id,
        roles=service.get_user_roles(user_id),
        permissions=permissions,
        overrides=overrides,
    )


@router.get("/me/permissions", response_model=UserPermissions)
async def get_my_permissions(
    current_user: User = Depends(get_current_user),
    service: RBACService = Depends(_service),
) -> UserPermissions:
    return _build_user_permissions(service, current_user.id)


@router.get(
    "/{user_id}/roles",
    response_model=list[str],
    dependencies=[Depends(require_permission("users", "read"))],
)
async def get_user_roles(user_id: int, service: RBACService = Depends(_service)) -> list[str]:
    return service.get_user_roles(user_id)


@router.post(
    "/{user_id}/roles",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("users", "write"))],
)
async def assign_user_role(
    user_id: int,
    payload: UserRoleAssignment,
    db: Session = Depends(get_db),
    service: RBACService = Depends(_service),
) -> None:
    if UserService(db).get_user(user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if service.get_role(payload.role_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    service.assign_role_to_user(user_id, payload.role_id)


@router.delete(
    "/{user_id}/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("users", "write"))],
)
async def remove_user_role(
    user_id: int,
    role_id: int,
    service: RBACService = Depends(_service),
) -> None:
    removed = service.remove_role_from_user(user_id, role_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User role assignment not found",
        )


@router.get(
    "/{user_id}/permissions",
    response_model=UserPermissions,
    dependencies=[Depends(require_permission("users", "read"))],
)
async def get_user_permissions(
    user_id: int,
    service: RBACService = Depends(_service),
) -> UserPermissions:
    return _build_user_permissions(service, user_id)


@router.post(
    "/{user_id}/permissions",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("users", "write"))],
)
async def set_user_permission_override(
    user_id: int,
    payload: UserPermissionAssignment,
    db: Session = Depends(get_db),
    service: RBACService = Depends(_service),
) -> None:
    if UserService(db).get_user(user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if service.get_permission_by_id(payload.permission_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found")

    service.assign_permission_to_user(user_id, payload.permission_id, payload.granted)


@router.delete(
    "/{user_id}/permissions/{permission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("users", "write"))],
)
async def remove_user_permission_override(
    user_id: int,
    permission_id: int,
    service: RBACService = Depends(_service),
) -> None:
    removed = service.remove_permission_from_user(user_id, permission_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User permission override not found",
        )
