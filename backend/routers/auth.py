from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from core.auth import AUTHENTICATE_HEADER, get_current_user_allow_password_change
from core.client_ip import resolve_client_host
from core.database import get_db
from core.models.users import User
from dependencies import (
    get_login_ip_rate_limiter,
    get_login_rate_limiter,
    get_login_user_rate_limiter,
)
from models.auth import (
    LoginRequest,
    PasswordChangeRequest,
    SessionResponse,
    TokenResponse,
    UserResponse,
)
from services.auth.auth_service import AuthenticationError, AuthService
from services.auth.login_rate_limiter import LoginRateLimiter, RateLimitExceededError
from services.auth.password_policy import PasswordPolicyError
from services.auth.rbac_service import RBACService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(
    request: Request,
    credentials: LoginRequest,
    db: Session = Depends(get_db),
    ip_limiter: LoginRateLimiter = Depends(get_login_ip_rate_limiter),
    user_limiter: LoginRateLimiter = Depends(get_login_user_rate_limiter),
) -> TokenResponse:
    # Two independent failure budgets (T1 / D2). The IP dimension is only as
    # trustworthy as the deployment's X-Forwarded-For chain (core/client_ip.py);
    # the username dimension cannot be evaded by header spoofing.
    ip_key = f"ip:{resolve_client_host(request)}"
    user_key = f"user:{credentials.username.lower()}"
    try:
        ip_limiter.assert_allowed(ip_key)
        user_limiter.assert_allowed(user_key)
    except RateLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts",
        ) from exc

    auth_service = AuthService(db)

    try:
        user = auth_service.authenticate_user(credentials.username, credentials.password)
    except AuthenticationError as exc:
        # Only failures consume budget: a legitimate user never pays for a
        # successful login, and a stranger cannot drain a user's budget by
        # presenting the correct password.
        ip_limiter.record(ip_key)
        user_limiter.record(user_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers=AUTHENTICATE_HEADER,
        ) from exc

    access_token, expires_in = auth_service.create_access_token(user)
    # Success clears the username bucket only; the IP bucket is never reset by
    # a success (a known-good account must not launder a stranger's IP budget).
    user_limiter.clear(user_key)

    return TokenResponse(access_token=access_token, expires_in=expires_in)


@router.get("/me", response_model=UserResponse)
def get_me(
    current_user: User = Depends(get_current_user_allow_password_change),
    db: Session = Depends(get_db),
) -> UserResponse:
    return _build_user_response(current_user, db)


@router.post("/change-password", response_model=SessionResponse)
def change_password(
    body: PasswordChangeRequest,
    current_user: User = Depends(get_current_user_allow_password_change),
    db: Session = Depends(get_db),
    rate_limiter: LoginRateLimiter = Depends(get_login_rate_limiter),
) -> SessionResponse:
    # Reuse the login rate limiter (a distinct key namespace) so the
    # current_password check above cannot be brute-forced.
    rate_limit_key = f"change-password:{current_user.id}"
    try:
        rate_limiter.check(rate_limit_key)
    except RateLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many password change attempts",
        ) from exc

    auth_service = AuthService(db)
    try:
        user = auth_service.change_password(
            current_user, body.current_password, body.new_password
        )
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    rate_limiter.clear(rate_limit_key)
    # change_password bumped token_version, so the caller's current token is now
    # stale. Hand back a fresh session so the client is not silently logged out
    # (worst in the forced-change flow). sid_iat defaults to now — a password
    # change deliberately restarts the absolute session clock.
    access_token, expires_in = auth_service.create_access_token(user)
    return SessionResponse(
        access_token=access_token,
        expires_in=expires_in,
        user=_build_user_response(user, db),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    current_user: User = Depends(get_current_user_allow_password_change),
    db: Session = Depends(get_db),
) -> None:
    """Revoke every outstanding token for the caller by bumping token_version.

    Uses ``get_current_user_allow_password_change`` so a user who is mid
    forced-password-change can still sign out.
    """
    AuthService(db).bump_token_version(current_user.id)


@router.post("/refresh", response_model=SessionResponse)
def refresh_token(
    request: Request,
    db: Session = Depends(get_db),
) -> SessionResponse:
    """Issue a new access token for the current user.

    Accepts expired access tokens so refresh can succeed when the JWT expires
    just before the keepalive call. Signature is still verified.
    """
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers=AUTHENTICATE_HEADER,
        )

    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers=AUTHENTICATE_HEADER,
        )

    auth_service = AuthService(db)
    try:
        user, access_token, expires_in = auth_service.refresh_access_token(token)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers=AUTHENTICATE_HEADER,
        ) from exc

    return SessionResponse(
        access_token=access_token,
        expires_in=expires_in,
        user=_build_user_response(user, db),
    )


def _build_user_response(user: User, db: Session) -> UserResponse:
    rbac = RBACService(db)

    return UserResponse(
        id=user.id,
        username=user.username,
        is_active=user.is_active,
        # bool(...): a synthetic/unflushed User (as in some tests) has this
        # column as None rather than the server_default until refreshed from
        # the database; a real persisted row is always a proper bool.
        must_change_password=bool(user.must_change_password),
        roles=rbac.get_user_roles(user.id),
        permissions=rbac.get_user_permission_strings(user.id),
    )
