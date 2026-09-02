from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
PASSWORD_CHANGE_REQUIRED_DETAIL = {
    "code": "password_change_required",
    "message": "You must change your password before continuing",
}


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


def _load_active_user(token_payload: dict[str, Any], db: Session) -> User:
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

    # Revocation (S5): every access token carries `tv` = the user's
    # token_version at mint time. A bump (logout, password / username change,
    # deactivation) makes every older token's `tv` stale. Both sides are
    # isinstance-guarded so a mocked user row with a non-int token_version does
    # not trip this by accident — same philosophy as the `must_change_password
    # is True` check in get_current_user / _require_active_user_id.
    token_tv = token_payload.get("tv")
    if (
        isinstance(user.token_version, int)
        and isinstance(token_tv, int)
        and token_tv != user.token_version
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers=AUTHENTICATE_HEADER,
        )

    # Absolute session lifetime (S5): `sid_iat` is the original login time,
    # carried unchanged through every refresh. Enforced whenever the claim is
    # present — every token this code mints has it; the refresh path
    # (AuthService.refresh_access_token) additionally *requires* it, so a token
    # without it cannot be renewed and dies at its own `exp`.
    sid_iat_raw = token_payload.get("sid_iat")
    if isinstance(sid_iat_raw, int | float):
        session_age = datetime.now(UTC) - datetime.fromtimestamp(sid_iat_raw, UTC)
        if session_age > timedelta(hours=settings.session_max_age_hours):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token",
                headers=AUTHENTICATE_HEADER,
            )

    return user


def get_current_user_allow_password_change(
    token_payload: dict[str, Any] = Depends(verify_token),
    db: Session = Depends(get_db),
) -> User:
    """Like ``get_current_user``, but does not block a user whose
    ``must_change_password`` flag is set.

    For ``/auth/me``, ``/auth/change-password``, and ``/auth/refresh`` only —
    every other endpoint must depend on ``get_current_user`` so a client
    cannot skip the forced password change by simply not reading the flag.
    """
    return _load_active_user(token_payload, db)


def get_current_user(
    user: User = Depends(get_current_user_allow_password_change),
) -> User:
    # `is True`, not truthy: must_change_password is a strictly-typed bool
    # column, always exactly True or False once loaded from a real row.
    if user.must_change_password is True:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=PASSWORD_CHANGE_REQUIRED_DETAIL,
        )
    return user


def _require_active_user_id(token_payload: dict[str, Any], db: Session) -> int:
    """Like ``get_current_user``, but returns the user id for callers (the
    ``require_*`` dependency factories below) that don't otherwise need the
    full ``User`` object.

    Permission/role dependencies are frequently used on their own (e.g.
    router-level ``dependencies=[Depends(require_permission(...))]``)
    without ``get_current_user`` in the chain, so both deactivation and the
    forced-password-change gate must be enforced here too — otherwise a
    still-valid JWT keeps working for a deactivated account, or a user who
    hasn't replaced a bootstrap/admin-set password, until it naturally
    expires.
    """
    user = _load_active_user(token_payload, db)

    # `is True`, not truthy: must_change_password is a strictly-typed bool
    # column, always exactly True or False once loaded from a real row.
    if user.must_change_password is True:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=PASSWORD_CHANGE_REQUIRED_DETAIL,
        )

    return user.id


def require_permission(resource: str, action: str):
    def permission_checker(
        token_payload: dict[str, Any] = Depends(verify_token),
        db: Session = Depends(get_db),
    ) -> dict[str, Any]:
        user_id = _require_active_user_id(token_payload, db)

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
        user_id = _require_active_user_id(token_payload, db)

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
        user_id = _require_active_user_id(token_payload, db)

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
        user_id = _require_active_user_id(token_payload, db)

        if not RBACService(db).has_role(user_id, role_name):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role denied: {role_name} required",
            )

        return token_payload

    return role_checker
