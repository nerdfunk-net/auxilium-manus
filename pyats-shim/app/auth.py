"""Bearer-token auth dependency for the pyATS shim's job endpoint."""

from __future__ import annotations

import hmac

from fastapi import Depends, Header, HTTPException, status

from app.config import ShimSettings, get_settings


def require_bearer_token(
    authorization: str | None = Header(default=None),
    settings: ShimSettings = Depends(get_settings),
) -> None:
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(token, settings.token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid bearer token")
