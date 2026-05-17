from __future__ import annotations

from collections import defaultdict, deque
from ipaddress import ip_address
from time import monotonic

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from core.auth import AUTHENTICATE_HEADER, get_current_user
from core.config import settings
from core.database import get_db
from core.models.users import User
from models.auth import LoginRequest, TokenResponse, UserResponse
from services.auth_service import AuthenticationError, AuthService

router = APIRouter(prefix="/auth", tags=["auth"])
LOGIN_RATE_LIMIT_ATTEMPTS = 5
LOGIN_RATE_LIMIT_WINDOW_SECONDS = 60
login_attempts: defaultdict[str, deque[float]] = defaultdict(deque)


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    credentials: LoginRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    rate_limit_key = _get_rate_limit_key(request, credentials.username)
    _check_login_rate_limit(rate_limit_key)
    auth_service = AuthService(db)

    try:
        user = auth_service.authenticate_user(credentials.username, credentials.password)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers=AUTHENTICATE_HEADER,
        ) from exc

    access_token, expires_in = auth_service.create_access_token(user)
    login_attempts.pop(rate_limit_key, None)

    return TokenResponse(access_token=access_token, expires_in=expires_in)


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(current_user)


def _get_rate_limit_key(request: Request, username: str) -> str:
    client_host = _get_client_host(request)

    return f"{client_host}:{username.lower()}"


def _get_client_host(request: Request) -> str:
    direct_client_host = request.client.host if request.client else "unknown"

    if direct_client_host not in settings.trusted_proxy_ips:
        return direct_client_host

    forwarded_for = request.headers.get("x-forwarded-for")
    real_ip = request.headers.get("x-real-ip")
    forwarded_client = forwarded_for.split(",", maxsplit=1)[0].strip() if forwarded_for else real_ip

    if forwarded_client is None:
        return direct_client_host

    try:
        ip_address(forwarded_client)
    except ValueError:
        return direct_client_host

    return forwarded_client


def _check_login_rate_limit(rate_limit_key: str) -> None:
    now = monotonic()
    attempts = login_attempts[rate_limit_key]

    while attempts and now - attempts[0] > LOGIN_RATE_LIMIT_WINDOW_SECONDS:
        attempts.popleft()

    if len(attempts) >= LOGIN_RATE_LIMIT_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts",
        )

    attempts.append(now)
