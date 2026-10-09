"""Per-user rate limiting for expensive endpoints (S9).

    budget = rate_limited("git-sync", attempts=10, window_seconds=60)

    @router.post("/sync", dependencies=[Depends(budget)])

Keyed on the authenticated user id, so one user cannot starve the others and a shared
NAT'd office is not throttled as one client. Every call counts (success or failure).
Unlike login, a Redis outage falls back to an in-process window instead of failing closed:
this is protection against runaway use, not an authentication control.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, status

import service_factory
from core.auth import get_current_user
from core.models.users import User
from services.auth.login_rate_limiter import RateLimitExceededError

_BUCKET_BUDGETS: dict[str, tuple[int, int]] = {}


def rate_limited(bucket: str, *, attempts: int, window_seconds: int) -> Callable[..., None]:
    # A bucket name is one budget: the limiter is cached by name, so reusing a name with a
    # different budget would silently keep the first. Fail at import, not per request.
    registered = _BUCKET_BUDGETS.setdefault(bucket, (attempts, window_seconds))
    if registered != (attempts, window_seconds):
        raise ValueError(f"rate-limit bucket {bucket!r} is already used with a different budget")

    def dependency(current_user: User = Depends(get_current_user)) -> None:
        limiter = service_factory.build_user_rate_limiter(bucket, attempts, window_seconds)
        try:
            limiter.check(f"{bucket}:{current_user.id}")
        except RateLimitExceededError as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests; slow down and retry shortly",
                headers={"Retry-After": str(window_seconds)},
            ) from exc

    dependency.__name__ = f"rate_limited_{bucket}"
    return dependency
