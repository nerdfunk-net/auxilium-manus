from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.safe_http_errors import raise_internal_server_error
from models.rbac import UserAdminResponse, UserCreate, UserListResponse, UserUpdate
from services.auth.rbac_service import RBACService
from services.users.user_service import UserService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(get_current_user)])


def _user_service(db: Session = Depends(get_db)) -> UserService:
    return UserService(db)


def _rbac_service(db: Session = Depends(get_db)) -> RBACService:
    return RBACService(db)


def _to_response(user, rbac: RBACService) -> UserAdminResponse:  # noqa: ANN001
    return UserAdminResponse(
        id=user.id,
        username=user.username,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
        roles=rbac.get_user_roles(user.id),
    )


@router.get(
    "",
    response_model=UserListResponse,
    dependencies=[Depends(require_permission("users", "read"))],
)
async def list_users(
    service: UserService = Depends(_user_service),
    rbac: RBACService = Depends(_rbac_service),
) -> UserListResponse:
    return UserListResponse(users=[_to_response(u, rbac) for u in service.list_users()])


@router.post(
    "",
    response_model=UserAdminResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("users", "write"))],
)
async def create_user(
    payload: UserCreate,
    service: UserService = Depends(_user_service),
    rbac: RBACService = Depends(_rbac_service),
) -> UserAdminResponse:
    try:
        user = service.create_user(payload.username, payload.password, payload.is_active)
        return _to_response(user, rbac)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise_internal_server_error(logger, "Failed to create user", exc)


@router.get(
    "/{user_id}",
    response_model=UserAdminResponse,
    dependencies=[Depends(require_permission("users", "read"))],
)
async def get_user(
    user_id: int,
    service: UserService = Depends(_user_service),
    rbac: RBACService = Depends(_rbac_service),
) -> UserAdminResponse:
    user = service.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return _to_response(user, rbac)


@router.put(
    "/{user_id}",
    response_model=UserAdminResponse,
    dependencies=[Depends(require_permission("users", "write"))],
)
async def update_user(
    user_id: int,
    payload: UserUpdate,
    service: UserService = Depends(_user_service),
    rbac: RBACService = Depends(_rbac_service),
) -> UserAdminResponse:
    try:
        user = service.update_user(
            user_id,
            username=payload.username,
            password=payload.password,
            is_active=payload.is_active,
        )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists",
        ) from exc

    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return _to_response(user, rbac)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("users", "delete"))],
)
async def delete_user(user_id: int, service: UserService = Depends(_user_service)) -> None:
    deleted = service.delete_user(user_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


@router.patch(
    "/{user_id}/activate",
    response_model=UserAdminResponse,
    dependencies=[Depends(require_permission("users", "write"))],
)
async def set_user_active(
    user_id: int,
    is_active: bool,
    service: UserService = Depends(_user_service),
    rbac: RBACService = Depends(_rbac_service),
) -> UserAdminResponse:
    user = service.set_active(user_id, is_active)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return _to_response(user, rbac)
