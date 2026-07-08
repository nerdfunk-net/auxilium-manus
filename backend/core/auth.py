from __future__ import annotations

from typing import Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from sqlalchemy.orm import Session

from core.config import settings
from core.database import get_db
from core.models.users import User
from repositories.user_repository import UserRepository
from services.auth.rbac_service import RBACService

bearer_scheme = HTTPBearer(auto_error=False)
AUTHENTICATE_HEADER = {"WWW-Authenticate": "Bearer"}


def verify_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, Any]:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers=AUTHENTICATE_HEADER,
        )

    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.secret_key,
            algorithms=["HS256"],
        )
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers=AUTHENTICATE_HEADER,
        ) from exc

    return payload


def get_current_user(
    token_payload: dict[str, Any] = Depends(verify_token),
    db: Session = Depends(get_db),
) -> User:
    user_id = token_payload.get("user_id")

    if not isinstance(user_id, int):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers=AUTHENTICATE_HEADER,
        )

    user = UserRepository(db).get_by_id(user_id)

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers=AUTHENTICATE_HEADER,
        )

    return user


def _require_user_id(token_payload: dict[str, Any]) -> int:
    user_id = token_payload.get("user_id")

    if not isinstance(user_id, int):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers=AUTHENTICATE_HEADER,
        )

    return user_id


def require_permission(resource: str, action: str):
    def permission_checker(
        token_payload: dict[str, Any] = Depends(verify_token),
        db: Session = Depends(get_db),
    ) -> dict[str, Any]:
        user_id = _require_user_id(token_payload)

        if not RBACService(db).has_permission(user_id, resource, action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {resource}:{action} required",
            )

        return token_payload

    return permission_checker


def require_any_permission(checks: list[tuple[str, str]]):
    def permission_checker(
        token_payload: dict[str, Any] = Depends(verify_token),
        db: Session = Depends(get_db),
    ) -> dict[str, Any]:
        user_id = _require_user_id(token_payload)

        if not RBACService(db).check_any_permission(user_id, checks):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: none of the required permissions are granted",
            )

        return token_payload

    return permission_checker


def require_all_permissions(checks: list[tuple[str, str]]):
    def permission_checker(
        token_payload: dict[str, Any] = Depends(verify_token),
        db: Session = Depends(get_db),
    ) -> dict[str, Any]:
        user_id = _require_user_id(token_payload)

        if not RBACService(db).check_all_permissions(user_id, checks):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: not all required permissions are granted",
            )

        return token_payload

    return permission_checker


def require_role(role_name: str):
    def role_checker(
        token_payload: dict[str, Any] = Depends(verify_token),
        db: Session = Depends(get_db),
    ) -> dict[str, Any]:
        user_id = _require_user_id(token_payload)

        if not RBACService(db).has_role(user_id, role_name):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role denied: {role_name} required",
            )

        return token_payload

    return role_checker
