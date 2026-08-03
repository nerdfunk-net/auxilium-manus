# Refactoring Plan — FABLE-ANALYSIS Remaining Items

> Based on: `doc/FABLE-ANALYSIS.md`, the items **not** already closed by `doc/refactoring/FABLE_PRIO.md`
> Steps 1–11 (all of which are done — see the "Update (2026-08-02)" note at the top of
> `FABLE-ANALYSIS.md`). This plan covers §4.5, §4.6, §4.7 (never in `FABLE_PRIO.md`'s scope) and
> resumes `FABLE_PRIO.md` Steps 12 (§7, testing debt) and 13 (§5.2, function decomposition), which
> that plan explicitly deferred as "sustained" / "opportunistic, do last."
> Date: 2026-08-03
> Status: Not started. Every "Code before" block below was read from the file at the stated lines
> during this pass (re-verified against the live tree, not copied from the original analysis) — one
> correction to `FABLE-ANALYSIS.md` §4.7 is called out in Step 3, where the live code turned out to
> already do more than the analysis credited it for.

This plan follows the same discipline as `FABLE_PRIO.md`: every mechanical/low-risk item (Steps 1–3)
gets a full "code before / code after" diff, ready to apply without re-reading the source. Steps 4–5
(§5.2, §7) are inherently open-ended — 75 functions over 80 lines and a 27-point coverage gap cannot
honestly be reduced to a frozen diff — so each gets one complete worked example (a real decomposition,
a real new test file) plus a precise target list and procedure, exactly as `FABLE_PRIO.md` Steps 12–13
did.

---

## Implementation Order

| # | Step | Analysis ref | Risk |
|---|---|---|---|
| 1 | Gate Nautobot/ISE `test-connection` on `write` permission; stop echoing raw exception text | §4.5 | low |
| 2 | Redis-backed login rate limiting, shared across worker processes, bounded memory | §4.6 | low — new Redis dependency already exists in this codebase; degrades to today's in-process behavior if Redis is down |
| 3 | Record §4.7 informational items as documented, accepted risk (one correction: verify_ssl logging is already complete) | §4.7 | none — docs only |
| 4 | Decompose `update_nautobot_device/executor.py` (worked example); target list for the remaining 9 longest functions | §5.2 | medium — touches an executor; full suite must stay green after |
| 5 | Testing debt: worked example test file for the new helpers from Step 4; refreshed sustained-effort target list | §7 | n/a — sustained effort, not a single patch |

Run the full test suite and all four regression guards after **every** step:

```bash
cd backend
source ../.venv/bin/activate
ruff check .
python -m pytest -q
python scripts/check_asyncio_run.py
python scripts/check_http_500_leaks.py
python scripts/check_router_repositories.py
python scripts/check_text_sql.py
```

---

## Step 1: Gate Test-Connection Endpoints, Stop Echoing Raw Exception Text (§4.5)

**What:** `POST /sources/nautobot/test-connection` and `POST /sources/ise/{source_id}/test-connection`
accept attacker-influenced connection parameters (arbitrary URL for Nautobot; a configured source's URL
for ISE) and make the backend connect to them, gated only by the **read** permission of the respective
router (`routers/sources/nautobot/ops.py:45`, `routers/sources/ise/ops.py:43`). On failure, both return
the raw exception text verbatim in a 200 response body (`f"Connection failed: {exc}"`), which is a
oracle for probing hosts/ports on the internal management network that any `sources.*:read` holder can
use.

**Why:** `rename_group` in the same file (`routers/sources/nautobot/ops.py:112-116`) already establishes
the pattern of stacking a stricter route-level permission on top of the router-level one — these
endpoints exist to *configure* sources, not merely to view them, so `write` is the correct bar, exactly
like `rename_group`. Sanitizing the message removes the probing oracle without losing debuggability: a
correlatable reference replaces raw exception text, and the full exception still goes to the server log.

**Note:** an SSRF guard (`core/safe_urls.py::validate_outbound_http_url`, used by both
`services/nautobot/client.py` and `services/ise/client.py`) already blocks loopback, link-local, and
cloud-metadata addresses — this was added after `FABLE-ANALYSIS.md`'s date and narrows the residual risk
from "raw SSRF" to "port/service probing of the on-prem management network," which is still real (RFC
1918 addresses are intentionally allowed, by design, for on-prem Nautobot/ISE — see
`core/safe_urls.py:77`) and still worth the two mitigations below.

**Files:** `backend/routers/sources/nautobot/ops.py`, `backend/routers/sources/ise/ops.py`

### Code before — `backend/routers/sources/nautobot/ops.py` (imports, lines 1–17)

```python
"""Nautobot source operations — preview, field metadata, resolve, analyze."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

import service_factory
from core.auth import get_current_user, require_permission
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from dependencies import (
    get_inventory_service,
    nautobot_credentials_from_body,
    nautobot_credentials_from_query,
)
```

### Code after

```python
"""Nautobot source operations — preview, field metadata, resolve, analyze."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status

import service_factory
from core.auth import get_current_user, require_permission
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from dependencies import (
    get_inventory_service,
    nautobot_credentials_from_body,
    nautobot_credentials_from_query,
)
```

### Code before — `backend/routers/sources/nautobot/ops.py:61-97`

```python
@router.post("/test-connection", response_model=NautobotTestConnectionResponse)
async def test_connection(
    request: NautobotTestConnectionRequest,
    _: User = Depends(get_current_user),
) -> NautobotTestConnectionResponse:
    """Test Nautobot connectivity using form values (does not require a saved source)."""
    credentials = service_factory.credentials_from_connection(
        request.url.strip(),
        request.token.strip(),
        request.timeout,
        verify_ssl=request.verify_ssl,
    )
    nautobot = service_factory.get_nautobot_app_service()
    try:
        status_payload = await nautobot.test_connection(credentials)
        version = ""
        if isinstance(status_payload, dict):
            version = str(
                status_payload.get("nautobot-version")
                or status_payload.get("nautobot_version")
                or ""
            ).strip()
        message = (
            f"Connection successful (Nautobot {version})"
            if version
            else "Connection successful"
        )
        return NautobotTestConnectionResponse(success=True, message=message)
    except NautobotValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except NautobotAPIError as exc:
        return NautobotTestConnectionResponse(
            success=False,
            message=f"Connection failed: {exc}",
        )
    except Exception as exc:
        raise_internal_server_error(logger, "Nautobot test connection failed: ", exc)
```

### Code after

```python
@router.post(
    "/test-connection",
    response_model=NautobotTestConnectionResponse,
    dependencies=[Depends(require_permission("sources.nautobot", "write"))],
)
async def test_connection(
    request: NautobotTestConnectionRequest,
    _: User = Depends(get_current_user),
) -> NautobotTestConnectionResponse:
    """Test Nautobot connectivity using form values (does not require a saved source)."""
    credentials = service_factory.credentials_from_connection(
        request.url.strip(),
        request.token.strip(),
        request.timeout,
        verify_ssl=request.verify_ssl,
    )
    nautobot = service_factory.get_nautobot_app_service()
    try:
        status_payload = await nautobot.test_connection(credentials)
        version = ""
        if isinstance(status_payload, dict):
            version = str(
                status_payload.get("nautobot-version")
                or status_payload.get("nautobot_version")
                or ""
            ).strip()
        message = (
            f"Connection successful (Nautobot {version})"
            if version
            else "Connection successful"
        )
        return NautobotTestConnectionResponse(success=True, message=message)
    except NautobotValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except NautobotAPIError as exc:
        error_id = uuid.uuid4()
        logger.warning("Nautobot test connection failed (error_id=%s): %s", error_id, exc)
        return NautobotTestConnectionResponse(
            success=False,
            message=f"Connection failed (ref: {error_id}). Check the URL, token, and network reachability.",
        )
    except Exception as exc:
        raise_internal_server_error(logger, "Nautobot test connection failed: ", exc)
```

`require_permission` and `Depends` are already imported (used by `rename_group` two functions below in
the same file) — no new import needed beyond `uuid`.

### Code before — `backend/routers/sources/ise/ops.py` (imports, lines 1–7)

```python
"""Cisco ISE network device CRUD and connectivity check, per configured source."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
```

### Code after

```python
"""Cisco ISE network device CRUD and connectivity check, per configured source."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
```

### Code before — `backend/routers/sources/ise/ops.py:261-278`

```python
@router.post("/test-connection", response_model=ISETestConnectionResponse)
async def test_connection(
    source_id: str,
    _: User = Depends(get_current_user),
    config: ISESourceConfigService = Depends(get_ise_source_config_service),
) -> ISETestConnectionResponse:
    device_service = _resolve_device_service(source_id, config)
    try:
        await device_service.test_connection()
        return ISETestConnectionResponse(success=True, message="Connection successful")
    except ISEValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ISEAPIError as exc:
        return ISETestConnectionResponse(success=False, message=f"Connection failed: {exc}")
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "ISE test connection failed: ", exc)
```

### Code after

```python
@router.post(
    "/test-connection",
    response_model=ISETestConnectionResponse,
    dependencies=[Depends(require_permission("sources.ise", "write"))],
)
async def test_connection(
    source_id: str,
    _: User = Depends(get_current_user),
    config: ISESourceConfigService = Depends(get_ise_source_config_service),
) -> ISETestConnectionResponse:
    device_service = _resolve_device_service(source_id, config)
    try:
        await device_service.test_connection()
        return ISETestConnectionResponse(success=True, message="Connection successful")
    except ISEValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ISEAPIError as exc:
        error_id = uuid.uuid4()
        logger.warning("ISE test connection failed (error_id=%s): %s", error_id, exc)
        return ISETestConnectionResponse(
            success=False,
            message=f"Connection failed (ref: {error_id}). Check the source configuration and network reachability.",
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "ISE test connection failed: ", exc)
```

`require_permission` is already imported in this file (used by `create_device`, `update_device`, etc.
at lines 180, 206, 236…) — confirmed `sources.ise:write` and `sources.nautobot:write` are both
pre-existing, already-granted permission tuples (used at `nautobot/crud.py:33,215,301`,
`nautobot/ops.py:115`, `ise/crud.py:70,100`, `ise/ops.py:180,206,285,358,396,472`) — nothing new to
provision in RBAC.

### Verification

```bash
cd backend
python -m pytest -q tests/unit -k "source_connection or nautobot or ise"
python -m pytest -q
```

Manual check (server running, logged in as a user with `sources.nautobot:read` but not `:write`):
`POST /api/sources/nautobot/test-connection` should now return `403`. As a `:write` holder, a failing
connection attempt should return `{"success": false, "message": "Connection failed (ref: <uuid>)...."}`
with the full exception detail present only in the server log, correlated by that same ref.

---

## Step 2: Redis-Backed Login Rate Limiting (§4.6)

**What:** `routers/auth.py`'s `login_attempts: defaultdict[str, deque[float]]` is a per-process,
in-memory structure. Under multiple uvicorn workers (or any horizontally-scaled deployment) each worker
has its own independent counter, so the effective limit multiplies by worker count; a process restart
resets it entirely. Separately, the dict only shrinks on a *successful* login
(`login_attempts.pop(rate_limit_key, None)`, `routers/auth.py:44`) — a key that only ever sees failed
attempts (or a one-time successful login from an IP that never returns) keeps an empty `deque` in the
dict forever, so memory grows without bound over the life of the process.

**Why:** Redis is already a first-class dependency in this codebase (`core/config.py`'s `redis_url`,
`services/cache/redis_cache_service.py`) — moving the rate-limit counter there makes it correct across
workers and bounds its own memory footprint via Redis `EXPIRE`, for the same reason the analysis
suggests it. The new limiter degrades to today's in-process behavior (not a hard failure) if Redis is
briefly unreachable, matching the existing fail-soft precedent set by
`service_factory.build_cache_service()` (which returns `None` on a Redis connection error rather than
crashing the app).

**New file:** `backend/services/auth/login_rate_limiter.py`

```python
"""Redis-backed login rate limiting, shared across worker processes.

Replaces the per-process ``defaultdict`` limiter that used to live in
``routers/auth.py`` — see doc/FABLE-ANALYSIS.md §4.6. Falls back to an
in-process sliding window when Redis is unreachable at check time, so a
transient Redis outage degrades rate-limit fidelity (per-worker instead of
global) rather than blocking login entirely, mirroring the fail-soft pattern
already used by ``service_factory.build_cache_service()``.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

import redis

logger = logging.getLogger(__name__)

LOGIN_RATE_LIMIT_ATTEMPTS = 5
LOGIN_RATE_LIMIT_WINDOW_SECONDS = 60


class RateLimitExceededError(Exception):
    """Raised when a rate-limit key has exceeded its attempt budget."""


class LoginRateLimiter:
    """Sliding-window login-attempt limiter.

    Uses one Redis sorted set per key (member and score are both the attempt
    timestamp): entries older than the window are trimmed on every check via
    ``ZREMRANGEBYSCORE``, then ``ZCARD`` gives the current attempt count. This
    is the standard sliding-window-log pattern and keeps Redis memory bounded
    without a background sweep — ``EXPIRE`` on the key means an abandoned key
    (no further attempts) disappears on its own after the window elapses,
    unlike the previous in-process dict, which kept an empty deque forever
    once touched.
    """

    def __init__(self, redis_url: str, key_prefix: str = "manus-login-rl") -> None:
        # redis.from_url does not connect eagerly, so constructing this is
        # always safe even if Redis is down — failures only surface, and are
        # only handled, inside check()/clear().
        self._redis = redis.from_url(redis_url, decode_responses=True)
        self._prefix = key_prefix
        self._fallback_attempts: defaultdict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        """Raise RateLimitExceededError if key is over budget; else record this attempt."""
        try:
            self._check_redis(key)
        except redis.RedisError:
            logger.warning(
                "Login rate limiter: Redis unavailable, using in-process fallback for this check"
            )
            self._check_fallback(key)

    def clear(self, key: str) -> None:
        """Reset a key's attempt history (called after a successful login)."""
        try:
            self._redis.delete(self._redis_key(key))
        except redis.RedisError:
            pass
        self._fallback_attempts.pop(key, None)

    def _redis_key(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    def _check_redis(self, key: str) -> None:
        redis_key = self._redis_key(key)
        now = time.time()
        window_start = now - LOGIN_RATE_LIMIT_WINDOW_SECONDS

        trim_and_count = self._redis.pipeline()
        trim_and_count.zremrangebyscore(redis_key, 0, window_start)
        trim_and_count.zcard(redis_key)
        _removed, attempt_count = trim_and_count.execute()

        if attempt_count >= LOGIN_RATE_LIMIT_ATTEMPTS:
            raise RateLimitExceededError(key)

        record_attempt = self._redis.pipeline()
        record_attempt.zadd(redis_key, {f"{now!r}": now})
        record_attempt.expire(redis_key, LOGIN_RATE_LIMIT_WINDOW_SECONDS)
        record_attempt.execute()

    def _check_fallback(self, key: str) -> None:
        now = time.monotonic()
        attempts = self._fallback_attempts[key]

        while attempts and now - attempts[0] > LOGIN_RATE_LIMIT_WINDOW_SECONDS:
            attempts.popleft()

        if len(attempts) >= LOGIN_RATE_LIMIT_ATTEMPTS:
            raise RateLimitExceededError(key)

        attempts.append(now)
```

`time.time()` (wall clock) is used for the Redis-backed path deliberately, not `time.monotonic()` —
monotonic clocks are per-process and not comparable across the multiple uvicorn workers that share the
same Redis key, whereas wall-clock timestamps are. The in-process fallback keeps `monotonic()` (as the
original code did) since it never leaves the current process.

### Code before — `backend/service_factory.py` (imports and globals, lines 1–23)

```python
"""Service factory for constructing application services."""

from __future__ import annotations

from sqlalchemy.orm import Session

from core.config import settings
from repositories.inventory_repository import InventoryRepository
from services.cache.redis_cache_service import RedisCacheService
from services.ise.client import ISEService
from services.ise.credentials import ISECredentials
from services.ise.network_device_group_service import ISENetworkDeviceGroupService
from services.ise.network_device_service import ISENetworkDeviceService
from services.ise.source_config_service import ISESourceConfigService
from services.nautobot.client import NautobotService
from services.nautobot.credentials import NautobotCredentials
from services.nautobot.metadata_service import NautobotMetadataService
from services.sources.nautobot.persistence_service import InventoryService
from services.sources.nautobot.source_service import NautobotSourceService

_cache_service: RedisCacheService | None = None
_nautobot_service: NautobotService | None = None
_ise_service: ISEService | None = None
```

### Code after

```python
"""Service factory for constructing application services."""

from __future__ import annotations

from sqlalchemy.orm import Session

from core.config import settings
from repositories.inventory_repository import InventoryRepository
from services.auth.login_rate_limiter import LoginRateLimiter
from services.cache.redis_cache_service import RedisCacheService
from services.ise.client import ISEService
from services.ise.credentials import ISECredentials
from services.ise.network_device_group_service import ISENetworkDeviceGroupService
from services.ise.network_device_service import ISENetworkDeviceService
from services.ise.source_config_service import ISESourceConfigService
from services.nautobot.client import NautobotService
from services.nautobot.credentials import NautobotCredentials
from services.nautobot.metadata_service import NautobotMetadataService
from services.sources.nautobot.persistence_service import InventoryService
from services.sources.nautobot.source_service import NautobotSourceService

_cache_service: RedisCacheService | None = None
_nautobot_service: NautobotService | None = None
_ise_service: ISEService | None = None
_login_rate_limiter: LoginRateLimiter | None = None
```

### Code before — `backend/service_factory.py:64-76` (`build_cache_service`)

```python
def build_cache_service() -> RedisCacheService | None:
    global _cache_service
    if _cache_service is not None:
        return _cache_service
    try:
        _cache_service = RedisCacheService(
            redis_url=settings.redis_url,
            key_prefix=settings.redis_key_prefix,
        )
        return _cache_service
    except Exception:
        return None
```

### Code after (new function added directly below, `build_cache_service` unchanged)

```python
def build_cache_service() -> RedisCacheService | None:
    global _cache_service
    if _cache_service is not None:
        return _cache_service
    try:
        _cache_service = RedisCacheService(
            redis_url=settings.redis_url,
            key_prefix=settings.redis_key_prefix,
        )
        return _cache_service
    except Exception:
        return None


def build_login_rate_limiter() -> LoginRateLimiter:
    global _login_rate_limiter
    if _login_rate_limiter is None:
        _login_rate_limiter = LoginRateLimiter(redis_url=settings.redis_url)
    return _login_rate_limiter
```

`build_login_rate_limiter` does not need `build_cache_service`'s try/except: `LoginRateLimiter.__init__`
only calls `redis.from_url(...)`, which does not connect — unlike `RedisCacheService.__init__`, which
eagerly calls `self._redis.exists(...)` and can raise immediately. Redis reachability is only ever
tested (and only ever falls back) inside `LoginRateLimiter.check()`.

### Code before — `backend/dependencies.py:58-67`

```python
def get_cache_service():
    return service_factory.build_cache_service()


def get_git_debug_service():
    return service_factory.build_git_debug_service()
```

### Code after

```python
def get_cache_service():
    return service_factory.build_cache_service()


def get_git_debug_service():
    return service_factory.build_git_debug_service()


def get_login_rate_limiter() -> LoginRateLimiter:
    return service_factory.build_login_rate_limiter()
```

Add `from services.auth.login_rate_limiter import LoginRateLimiter` to `dependencies.py`'s imports.

### Code before — `backend/routers/auth.py` (full file)

```python
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
from models.auth import LoginRequest, SessionResponse, TokenResponse, UserResponse
from services.auth.auth_service import AuthenticationError, AuthService
from services.auth.rbac_service import RBACService

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
async def get_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserResponse:
    return _build_user_response(current_user, db)


@router.post("/refresh", response_model=SessionResponse)
async def refresh_token(
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
        roles=rbac.get_user_roles(user.id),
        permissions=rbac.get_user_permission_strings(user.id),
    )


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
```

### Code after (full file)

```python
from __future__ import annotations

from ipaddress import ip_address

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from core.auth import AUTHENTICATE_HEADER, get_current_user
from core.config import settings
from core.database import get_db
from core.models.users import User
from dependencies import get_login_rate_limiter
from models.auth import LoginRequest, SessionResponse, TokenResponse, UserResponse
from services.auth.auth_service import AuthenticationError, AuthService
from services.auth.login_rate_limiter import LoginRateLimiter, RateLimitExceededError
from services.auth.rbac_service import RBACService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    credentials: LoginRequest,
    db: Session = Depends(get_db),
    rate_limiter: LoginRateLimiter = Depends(get_login_rate_limiter),
) -> TokenResponse:
    rate_limit_key = _get_rate_limit_key(request, credentials.username)
    try:
        rate_limiter.check(rate_limit_key)
    except RateLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts",
        ) from exc

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
    rate_limiter.clear(rate_limit_key)

    return TokenResponse(access_token=access_token, expires_in=expires_in)


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserResponse:
    return _build_user_response(current_user, db)


@router.post("/refresh", response_model=SessionResponse)
async def refresh_token(
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
        roles=rbac.get_user_roles(user.id),
        permissions=rbac.get_user_permission_strings(user.id),
    )


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
```

`LOGIN_RATE_LIMIT_ATTEMPTS`/`LOGIN_RATE_LIMIT_WINDOW_SECONDS` move into the new module as its own
constants (still `5`/`60`, unchanged values) — they are not made environment-configurable here, since
they weren't before either; this step fixes the cross-worker/unbounded-memory bug, not scope-creeps into
new configurability.

### New test — `backend/tests/unit/test_login_rate_limiter.py`

```python
"""Tests for the Redis-backed login rate limiter — see doc/FABLE-ANALYSIS.md §4.6."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

import redis

from services.auth.login_rate_limiter import (
    LOGIN_RATE_LIMIT_ATTEMPTS,
    LoginRateLimiter,
    RateLimitExceededError,
)


class LoginRateLimiterRedisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.limiter = LoginRateLimiter(redis_url="redis://localhost:6379/0")
        self.limiter._redis = MagicMock()

    def test_allows_attempts_under_the_limit(self) -> None:
        self.limiter._redis.pipeline.return_value.execute.side_effect = [
            [0, LOGIN_RATE_LIMIT_ATTEMPTS - 1],
            [1, True],
        ]

        self.limiter.check("1.2.3.4:alice")  # must not raise

    def test_blocks_once_the_window_is_full(self) -> None:
        self.limiter._redis.pipeline.return_value.execute.side_effect = [
            [0, LOGIN_RATE_LIMIT_ATTEMPTS],
        ]

        with self.assertRaises(RateLimitExceededError):
            self.limiter.check("1.2.3.4:alice")

    def test_clear_removes_the_redis_key(self) -> None:
        self.limiter.clear("1.2.3.4:alice")

        self.limiter._redis.delete.assert_called_once_with("manus-login-rl:1.2.3.4:alice")

    def test_falls_back_to_in_process_limiter_when_redis_is_unreachable(self) -> None:
        self.limiter._redis.pipeline.side_effect = redis.ConnectionError("down")

        for _ in range(LOGIN_RATE_LIMIT_ATTEMPTS):
            self.limiter.check("1.2.3.4:bob")

        with self.assertRaises(RateLimitExceededError):
            self.limiter.check("1.2.3.4:bob")


if __name__ == "__main__":
    unittest.main()
```

No existing test referenced `routers.auth.login_attempts` or `_check_login_rate_limit` directly
(verified: `grep -rln "login_attempts\|_check_login_rate_limit" tests/ routers/` only matches
`routers/auth.py` itself), so no other test file needs updating for this move.

### Verification

```bash
cd backend
python -m pytest -q tests/unit/test_login_rate_limiter.py -v
python -m pytest -q
ruff check .
```

Manual check (Docker Redis running, per this project's dev-environment convention): log in with a wrong
password 5 times from the same client within 60s — the 6th attempt should return `429` — then confirm
the same behavior holds if you stop the dev backend process and start a second instance pointed at the
same Redis (proving the counter is now shared, not per-process).

---

## Step 3: Record §4.7 Informational Items as Documented, Accepted Risk (§4.7)

**What:** `FABLE-ANALYSIS.md` §4.7 lists four informational items. Re-reading each against the current
code during this pass turned up **one correction to the analysis itself**: the `verify_ssl=False`
logging gap it implies does not exist — both Nautobot request paths and the ISE client already log it.
The other three items are exactly as described and are genuinely "consider/state in docs" items, not
code defects — no source change is proposed for them. This step's only deliverable is a new
documentation file recording all four as reviewed, accepted risks with their rationale, so the next
person to read `FABLE-ANALYSIS.md` §4.7 doesn't have to re-derive this.

**Why:** CLAUDE.md's task-completion discipline ("verify no references remain," full removal/fix
cycles) is about not leaving dangling TODOs. An informational finding that the team has looked at and
decided not to act on is not a TODO — writing that decision down (with the "why") is the correct closure
for it, and is cheaper and more honest than inventing code changes for accepted risk.

**Correction — verify_ssl logging (§4.7, first bullet):** the analysis text doesn't claim a gap
explicitly, but a naive reading of "logged per request" could be checked and found incomplete; it isn't.
Confirmed present in all three call sites:

- `services/nautobot/client.py:81-85` (`graphql_query`) — `logger.warning("Nautobot GraphQL with verify_ssl=False url_host=%s", ...)`
- `services/nautobot/client.py:131-135` (`rest_request`) — `logger.warning("Nautobot REST with verify_ssl=False url_host=%s", ...)`
- `services/ise/client.py:68-72` (`ers_request`) — `logger.warning("ISE request with verify_ssl=False url_host=%s", ...)`

No code change needed here.

**New file:** `backend/../doc/SECURITY-NOTES.md` (repo root `doc/`, alongside `FABLE-ANALYSIS.md`)

```markdown
# Security Notes — Accepted Risks

This file records security-adjacent findings from `doc/FABLE-ANALYSIS.md` §4.7 that were reviewed and
intentionally left as-is, with the reasoning, so they aren't re-investigated from scratch later.

## `verify_ssl=False` support (Nautobot, ISE clients)

`services/nautobot/client.py` and `services/ise/client.py` each keep a second, non-verifying
`httpx.AsyncClient` pool because on-prem Nautobot/ISE instances in NetDevOps environments commonly
present self-signed certificates. Every request made with `verify_ssl=False` is logged at `WARNING`
with the target host (`graphql_query`, `rest_request` in the Nautobot client; `ers_request` in the ISE
client — all three call sites confirmed present). **Accepted as-is**: there is currently no UI/RBAC gate
specifically preventing `verify_ssl=False` sources in a production configuration; adding one is worth
doing if this product is ever deployed against untrusted/adversarial networks rather than a managed
internal one.

## Netmiko: no SSH host-key verification

`services/network/netmiko/connection.py` builds `ConnectHandler(**device_params)` with no host-key
checking parameters; Netmiko's default behavior auto-accepts unknown host keys (equivalent to
`StrictHostKeyChecking=no`). **Accepted as-is**: standard practice for NetDevOps automation tooling
targeting a known device inventory, but worth stating explicitly here since it's a real MITM exposure if
the management network is ever untrusted.

## Git credentials visible in process argv

`services/sources/git/git_source_service.py` embeds HTTP basic-auth credentials into the remote URL
(`_build_auth_url`) and passes that URL directly in the `git clone`/`git push` argv
(`subprocess.run(cmd, ...)`), which is visible to other local users via `ps` on a shared host for the
duration of the subprocess call. Output (`stdout`/`stderr`) is correctly redacted before being returned
to the client or logged (`_redact_secrets`, called at both call sites) — only the argv-visibility window
is unaddressed. **Accepted as-is** for now; `GIT_ASKPASS` or a git credential-helper would close this
window if it's ever prioritized, since neither exposes the secret via argv.

## Git debug write endpoints (`test_write`/`test_delete`/`test_push`)

`services/git/debug_service.py`'s `test_write`, `test_delete`, and `test_push` perform real filesystem
writes and real pushes against configured git repositories. All three (plus a fourth, read-only,
diagnostic endpoint) are gated behind `require_permission("git.debug", "execute")` /
`require_permission("git.debug", "read")` in `routers/git/debug.py` — confirmed at the route-decorator
level for every endpoint in that file. **Accepted as-is**: the permission gate is correctly and
consistently applied; whether these debug endpoints should exist at all in a production build is a
product decision, not a code defect, and is out of scope for this plan.
```

### Verification

No code executes. Review by reading the new file back and cross-checking the three verify_ssl log
call-sites listed above still exist:

```bash
grep -n "verify_ssl=False" backend/services/nautobot/client.py backend/services/ise/client.py
```

---

## Step 4: Decompose the Largest `execute()`/Service Functions (§5.2) — Opportunistic

**What:** A fresh AST rescan (this pass) finds **75** functions over the 80-line threshold from
`coding-style.md` (`functions <50 lines`) — down from the 77 `FABLE-ANALYSIS.md` originally counted (2
were incidentally fixed by unrelated work since). The top 10 are essentially unchanged from the original
table (line numbers drifted by ~1 in a couple of cases; lengths identical):

| Lines | Location |
|---|---|
| 288 | `workflow_steps/deploy_rendered_template/executor.py:84` `execute` |
| 245 | `workflow_steps/update_nautobot_device/executor.py:83` `execute` |
| 243 | `services/git/debug_service.py:242` `test_push` |
| 240 | `services/nautobot/devices/update.py:49` `update_device` |
| 238 | `workflow_steps/add_to_ise/executor.py:122` `execute` |
| 219 | `workflow_steps/compare_data/executor.py:164` `execute` |
| 216 | `services/nautobot/managers/ip_manager.py:43` `ensure_ip_address_exists` |
| 202 | `workflow_steps/run_command/executor.py:78` `execute` |
| 197 | `workflow_steps/add_to_nautobot/executor.py:109` `execute` |
| 196 | `hatchet/workflows/workflow_run.py:400` `_dispatch_children` |

Two more just below the original cutoff are worth knowing about if this list needs an 11th/12th target
later: `services/sources/nautobot/evaluator.py:155` `_execute_condition` (186 lines) and
`services/nautobot/devices/interface_workflow.py:43` `update_device_interfaces` (180 lines).

**Why no full diff for all 10:** as `FABLE_PRIO.md` Step 13 already established for this same list,
reproducing 150–290-line function bodies verbatim goes stale the moment anyone touches the file, and
correctly splitting one requires reading the current body anyway. What follows instead is one **complete
worked example** — `update_nautobot_device` (rank 2, and also one of §7's under-tested executors, so it
pays a double dividend) — plus the same proven in-repo exemplar (`get_ise_tacacs_key/executor.py`) and
procedure for the rest.

**Worked example — `backend/workflow_steps/update_nautobot_device/executor.py` (full file)**

### Code before

```python
"""Executor for the update-nautobot-device workflow step."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import (
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from repositories.settings_repository import SettingsRepository
from services.artifacts import ArtifactService
from services.nautobot.credentials_bound_client import CredentialsBoundNautobotClient
from services.nautobot.devices.update import DeviceUpdateService
from services.settings.source_keys import build_source_key
from workflow_steps.common.nautobot_interfaces import (
    build_interfaces_from_config,
    normalize_interfaces,
)
from workflow_steps.common.nautobot_resolve import resolve_nautobot_device_id
from workflow_steps.common.update_field_expression import (
    build_resolved_update_data,
    config_has_enabled_update_fields,
    normalize_field_spec,
)

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "update-nautobot-device"


def _strip_empty(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return value


def _resolve_device_identifier(
    *,
    config: dict[str, Any],
    device: DeviceContext,
    nautobot_device_id: str | None,
) -> dict[str, Any]:
    raw_identifier = config.get("device_identifier") or {}
    mode = "from_context"
    if isinstance(raw_identifier, dict):
        mode = str(raw_identifier.get("mode") or "from_context").strip()

    if mode == "explicit" and isinstance(raw_identifier, dict):
        explicit_id = _strip_empty(raw_identifier.get("id"))
        explicit_name = _strip_empty(raw_identifier.get("name"))
        if explicit_id or explicit_name:
            identifier: dict[str, Any] = {}
            if explicit_id:
                identifier["id"] = explicit_id
            if explicit_name:
                identifier["name"] = explicit_name
            return identifier

    identifier = {}
    if nautobot_device_id:
        identifier["id"] = nautobot_device_id
    elif device.name:
        identifier["name"] = device.name
    elif device.primary_ip4:
        identifier["ip_address"] = device.primary_ip4
    return identifier


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service

    source_id = str(config.get("nautobot_source_id") or "").strip()
    if not source_id:
        raise ValueError(f"{_STEP_ID}: nautobot_source_id is not configured")

    raw_update_fields = config.get("update_fields") or {}
    if not isinstance(raw_update_fields, dict):
        raise ValueError(f"{_STEP_ID}: update_fields must be an object")

    interfaces = normalize_interfaces(
        build_interfaces_from_config(config, step_id=_STEP_ID),
        str(config.get("default_prefix_length") or "/24"),
    )
    if not config_has_enabled_update_fields(raw_update_fields) and not interfaces:
        raise ValueError(
            f"{_STEP_ID}: configure at least one enabled device field or interface to update"
        )

    add_prefix = bool(config.get("add_prefix", True))
    default_prefix_length = str(config.get("default_prefix_length") or "/24")
    sync_interfaces = bool(config.get("sync_interfaces", False))

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")

    setting_key = build_source_key("nautobot", source_id)
    setting = SettingsRepository(db).get_by_key(setting_key)
    if setting is None:
        raise ValueError(f"{_STEP_ID}: Nautobot source '{source_id}' not found in settings")

    nautobot_url = (setting.value or {}).get("url", "").strip()
    nautobot_token = (setting.value or {}).get("token", "").strip()
    nautobot_verify_ssl = bool((setting.value or {}).get("verify_ssl", True))
    if not nautobot_url or not nautobot_token:
        raise ValueError(f"{_STEP_ID}: Nautobot source '{source_id}' is missing url or token")

    credentials = service_factory.credentials_from_connection(
        nautobot_url, nautobot_token, verify_ssl=nautobot_verify_ssl
    )
    nautobot_service = service_factory.get_nautobot_app_service()
    bound_client = CredentialsBoundNautobotClient(nautobot_service, credentials)
    update_service = DeviceUpdateService(bound_client)

    identifier_mode = "from_context"
    raw_identifier = config.get("device_identifier") or {}
    if isinstance(raw_identifier, dict):
        identifier_mode = str(raw_identifier.get("mode") or "from_context")

    if identifier_mode == "explicit":
        device_items: list[tuple[str, DeviceContext | None]] = [
            ("explicit", None),
        ]
    elif not context.devices:
        raise ValueError(
            f"{_STEP_ID}: no devices in workflow context; "
            "connect an inventory step or use explicit device identifier"
        )
    else:
        device_items = list(context.devices.items())

    enabled_field_count = 0
    for key, raw in raw_update_fields.items():
        if key == "custom_fields" and isinstance(raw, dict):
            enabled_field_count += sum(1 for item in raw.values() if normalize_field_spec(item)[0])
            continue
        if normalize_field_spec(raw)[0]:
            enabled_field_count += 1

    logger.info(
        "%s started run_id=%s source_id=%s devices=%d enabled_fields=%d interfaces=%d",
        _STEP_ID,
        run.id,
        source_id,
        len(device_items),
        enabled_field_count,
        len(interfaces),
    )

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}

    async def update_one(
        device_key: str,
        device: DeviceContext | None,
    ) -> tuple[str, DeviceContext | None, bool, str | None]:
        try:
            nautobot_device_id: str | None = None
            if device is not None:
                nautobot_device_id = await resolve_nautobot_device_id(
                    nautobot_service=nautobot_service,
                    credentials=credentials,
                    device=device,
                )
                if nautobot_device_id is None:
                    err = DeviceError(
                        node_id=node_id,
                        step_id=_STEP_ID,
                        code="not_found",
                        message=(
                            f"No Nautobot device found for workflow device {device_key} "
                            f"(name={device.name!r}, ip={device.primary_ip4!r})"
                        ),
                    )
                    failed = device.model_copy(
                        update={
                            "status": DeviceStatus.FAILED,
                            "errors": [*device.errors, err],
                        }
                    )
                    return device_key, failed, False, None

            device_identifier = _resolve_device_identifier(
                config=config,
                device=device or DeviceContext(id=device_key, name=device_key, hostname=device_key),
                nautobot_device_id=nautobot_device_id,
            )
            if not any(device_identifier.get(k) for k in ("id", "name", "ip_address")):
                raise ValueError("device identifier must include id, name, or ip_address")

            resolved_device = device or DeviceContext(
                id=device_key,
                name=device_key,
                hostname=device_key,
            )
            update_data = build_resolved_update_data(
                device=resolved_device,
                raw_fields=raw_update_fields,
                run_id=str(context.run_id) if context.run_id else None,
            )

            result = await update_service.update_device(
                device_identifier=device_identifier,
                update_data=update_data,
                interfaces=interfaces or None,
                add_prefix=add_prefix,
                default_prefix_length=default_prefix_length,
                sync_interfaces=sync_interfaces,
            )

            interfaces_failed = int(result.get("interfaces_failed") or 0)
            if interfaces_failed > 0:
                raise RuntimeError(
                    f"{interfaces_failed} interface update(s) failed for device "
                    f"{result.get('device_name') or device_key}"
                )

            if device is None:
                device_name = result.get("device_name") or device_key
                placeholder = DeviceContext(
                    id=result.get("device_id") or device_key,
                    name=device_name,
                    hostname=device_name,
                    source="nautobot",
                    status=DeviceStatus.OK,
                )
                return device_key, placeholder, True, result.get("device_id")

            enriched = device.model_copy(
                update={
                    "id": str(result.get("device_id") or device.id),
                    "name": result.get("device_name") or device.name,
                    "source": "nautobot",
                    "status": DeviceStatus.OK,
                }
            )
            return device_key, enriched, True, result.get("device_id")
        except Exception as exc:
            message = str(exc)
            if device is None:
                placeholder = DeviceContext(
                    id=device_key,
                    name=device_key,
                    hostname=device_key,
                    source="nautobot",
                    status=DeviceStatus.FAILED,
                    errors=[
                        DeviceError(
                            node_id=node_id,
                            step_id=_STEP_ID,
                            code=type(exc).__name__.lower(),
                            message=message,
                        )
                    ],
                )
                return device_key, placeholder, False, None

            err = DeviceError(
                node_id=node_id,
                step_id=_STEP_ID,
                code=type(exc).__name__.lower(),
                message=message,
            )
            failed = device.model_copy(
                update={
                    "status": DeviceStatus.FAILED,
                    "errors": [*device.errors, err],
                }
            )
            return device_key, failed, False, None

    results = await asyncio.gather(
        *[update_one(device_key, device) for device_key, device in device_items]
    )

    for device_key, updated_device, ok, _resolved_id in results:
        if updated_device is None:
            continue
        if ok:
            success_devices[device_key] = updated_device
        else:
            failed_devices[device_key] = updated_device

    logger.info(
        "%s finished success=%d failure=%d run_id=%s",
        _STEP_ID,
        len(success_devices),
        len(failed_devices),
        run.id,
    )

    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": success_devices}),
        )
    ]
    if failed_devices:
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(update={"devices": failed_devices}),
            )
        )
    return outcomes
```

### Code after

```python
"""Executor for the update-nautobot-device workflow step."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import (
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from repositories.settings_repository import SettingsRepository
from services.artifacts import ArtifactService
from services.nautobot.client import NautobotService
from services.nautobot.credentials import NautobotCredentials
from services.nautobot.credentials_bound_client import CredentialsBoundNautobotClient
from services.nautobot.devices.update import DeviceUpdateService
from services.settings.source_keys import build_source_key
from workflow_steps.common.nautobot_interfaces import (
    build_interfaces_from_config,
    normalize_interfaces,
)
from workflow_steps.common.nautobot_resolve import resolve_nautobot_device_id
from workflow_steps.common.update_field_expression import (
    build_resolved_update_data,
    config_has_enabled_update_fields,
    normalize_field_spec,
)

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "update-nautobot-device"


@dataclass(frozen=True)
class _ParsedConfig:
    source_id: str
    raw_update_fields: dict[str, Any]
    interfaces: list[dict[str, Any]]
    add_prefix: bool
    default_prefix_length: str
    sync_interfaces: bool
    identifier_mode: str


def _strip_empty(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return value


def _resolve_device_identifier(
    *,
    config: dict[str, Any],
    device: DeviceContext,
    nautobot_device_id: str | None,
) -> dict[str, Any]:
    raw_identifier = config.get("device_identifier") or {}
    mode = "from_context"
    if isinstance(raw_identifier, dict):
        mode = str(raw_identifier.get("mode") or "from_context").strip()

    if mode == "explicit" and isinstance(raw_identifier, dict):
        explicit_id = _strip_empty(raw_identifier.get("id"))
        explicit_name = _strip_empty(raw_identifier.get("name"))
        if explicit_id or explicit_name:
            identifier: dict[str, Any] = {}
            if explicit_id:
                identifier["id"] = explicit_id
            if explicit_name:
                identifier["name"] = explicit_name
            return identifier

    identifier = {}
    if nautobot_device_id:
        identifier["id"] = nautobot_device_id
    elif device.name:
        identifier["name"] = device.name
    elif device.primary_ip4:
        identifier["ip_address"] = device.primary_ip4
    return identifier


def _parse_config(config: dict[str, Any]) -> _ParsedConfig:
    source_id = str(config.get("nautobot_source_id") or "").strip()
    if not source_id:
        raise ValueError(f"{_STEP_ID}: nautobot_source_id is not configured")

    raw_update_fields = config.get("update_fields") or {}
    if not isinstance(raw_update_fields, dict):
        raise ValueError(f"{_STEP_ID}: update_fields must be an object")

    interfaces = normalize_interfaces(
        build_interfaces_from_config(config, step_id=_STEP_ID),
        str(config.get("default_prefix_length") or "/24"),
    )
    if not config_has_enabled_update_fields(raw_update_fields) and not interfaces:
        raise ValueError(
            f"{_STEP_ID}: configure at least one enabled device field or interface to update"
        )

    raw_identifier = config.get("device_identifier") or {}
    identifier_mode = "from_context"
    if isinstance(raw_identifier, dict):
        identifier_mode = str(raw_identifier.get("mode") or "from_context")

    return _ParsedConfig(
        source_id=source_id,
        raw_update_fields=raw_update_fields,
        interfaces=interfaces,
        add_prefix=bool(config.get("add_prefix", True)),
        default_prefix_length=str(config.get("default_prefix_length") or "/24"),
        sync_interfaces=bool(config.get("sync_interfaces", False)),
        identifier_mode=identifier_mode,
    )


def _resolve_device_items(
    identifier_mode: str, context: WorkflowContext
) -> list[tuple[str, DeviceContext | None]]:
    if identifier_mode == "explicit":
        return [("explicit", None)]
    if not context.devices:
        raise ValueError(
            f"{_STEP_ID}: no devices in workflow context; "
            "connect an inventory step or use explicit device identifier"
        )
    return list(context.devices.items())


def _count_enabled_fields(raw_update_fields: dict[str, Any]) -> int:
    enabled_field_count = 0
    for key, raw in raw_update_fields.items():
        if key == "custom_fields" and isinstance(raw, dict):
            enabled_field_count += sum(1 for item in raw.values() if normalize_field_spec(item)[0])
            continue
        if normalize_field_spec(raw)[0]:
            enabled_field_count += 1
    return enabled_field_count


def _build_update_service(
    db: Any, source_id: str
) -> tuple[NautobotService, NautobotCredentials, DeviceUpdateService]:
    setting_key = build_source_key("nautobot", source_id)
    setting = SettingsRepository(db).get_by_key(setting_key)
    if setting is None:
        raise ValueError(f"{_STEP_ID}: Nautobot source '{source_id}' not found in settings")

    nautobot_url = (setting.value or {}).get("url", "").strip()
    nautobot_token = (setting.value or {}).get("token", "").strip()
    nautobot_verify_ssl = bool((setting.value or {}).get("verify_ssl", True))
    if not nautobot_url or not nautobot_token:
        raise ValueError(f"{_STEP_ID}: Nautobot source '{source_id}' is missing url or token")

    credentials = service_factory.credentials_from_connection(
        nautobot_url, nautobot_token, verify_ssl=nautobot_verify_ssl
    )
    nautobot_service = service_factory.get_nautobot_app_service()
    bound_client = CredentialsBoundNautobotClient(nautobot_service, credentials)
    return nautobot_service, credentials, DeviceUpdateService(bound_client)


async def _update_one_device(
    *,
    device_key: str,
    device: DeviceContext | None,
    config: dict[str, Any],
    context: WorkflowContext,
    node_id: str,
    nautobot_service: NautobotService,
    credentials: NautobotCredentials,
    update_service: DeviceUpdateService,
    parsed: _ParsedConfig,
) -> tuple[str, DeviceContext | None, bool, str | None]:
    try:
        nautobot_device_id: str | None = None
        if device is not None:
            nautobot_device_id = await resolve_nautobot_device_id(
                nautobot_service=nautobot_service,
                credentials=credentials,
                device=device,
            )
            if nautobot_device_id is None:
                err = DeviceError(
                    node_id=node_id,
                    step_id=_STEP_ID,
                    code="not_found",
                    message=(
                        f"No Nautobot device found for workflow device {device_key} "
                        f"(name={device.name!r}, ip={device.primary_ip4!r})"
                    ),
                )
                failed = device.model_copy(
                    update={
                        "status": DeviceStatus.FAILED,
                        "errors": [*device.errors, err],
                    }
                )
                return device_key, failed, False, None

        device_identifier = _resolve_device_identifier(
            config=config,
            device=device or DeviceContext(id=device_key, name=device_key, hostname=device_key),
            nautobot_device_id=nautobot_device_id,
        )
        if not any(device_identifier.get(k) for k in ("id", "name", "ip_address")):
            raise ValueError("device identifier must include id, name, or ip_address")

        resolved_device = device or DeviceContext(
            id=device_key,
            name=device_key,
            hostname=device_key,
        )
        update_data = build_resolved_update_data(
            device=resolved_device,
            raw_fields=parsed.raw_update_fields,
            run_id=str(context.run_id) if context.run_id else None,
        )

        result = await update_service.update_device(
            device_identifier=device_identifier,
            update_data=update_data,
            interfaces=parsed.interfaces or None,
            add_prefix=parsed.add_prefix,
            default_prefix_length=parsed.default_prefix_length,
            sync_interfaces=parsed.sync_interfaces,
        )

        interfaces_failed = int(result.get("interfaces_failed") or 0)
        if interfaces_failed > 0:
            raise RuntimeError(
                f"{interfaces_failed} interface update(s) failed for device "
                f"{result.get('device_name') or device_key}"
            )

        if device is None:
            device_name = result.get("device_name") or device_key
            placeholder = DeviceContext(
                id=result.get("device_id") or device_key,
                name=device_name,
                hostname=device_name,
                source="nautobot",
                status=DeviceStatus.OK,
            )
            return device_key, placeholder, True, result.get("device_id")

        enriched = device.model_copy(
            update={
                "id": str(result.get("device_id") or device.id),
                "name": result.get("device_name") or device.name,
                "source": "nautobot",
                "status": DeviceStatus.OK,
            }
        )
        return device_key, enriched, True, result.get("device_id")
    except Exception as exc:
        message = str(exc)
        if device is None:
            placeholder = DeviceContext(
                id=device_key,
                name=device_key,
                hostname=device_key,
                source="nautobot",
                status=DeviceStatus.FAILED,
                errors=[
                    DeviceError(
                        node_id=node_id,
                        step_id=_STEP_ID,
                        code=type(exc).__name__.lower(),
                        message=message,
                    )
                ],
            )
            return device_key, placeholder, False, None

        err = DeviceError(
            node_id=node_id,
            step_id=_STEP_ID,
            code=type(exc).__name__.lower(),
            message=message,
        )
        failed = device.model_copy(
            update={
                "status": DeviceStatus.FAILED,
                "errors": [*device.errors, err],
            }
        )
        return device_key, failed, False, None


def _build_outcomes(
    context: WorkflowContext,
    success_devices: dict[str, DeviceContext],
    failed_devices: dict[str, DeviceContext],
) -> list[StepOutcome]:
    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": success_devices}),
        )
    ]
    if failed_devices:
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(update={"devices": failed_devices}),
            )
        )
    return outcomes


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service

    parsed = _parse_config(config)

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")

    nautobot_service, credentials, update_service = _build_update_service(db, parsed.source_id)
    device_items = _resolve_device_items(parsed.identifier_mode, context)
    enabled_field_count = _count_enabled_fields(parsed.raw_update_fields)

    logger.info(
        "%s started run_id=%s source_id=%s devices=%d enabled_fields=%d interfaces=%d",
        _STEP_ID,
        run.id,
        parsed.source_id,
        len(device_items),
        enabled_field_count,
        len(parsed.interfaces),
    )

    results = await asyncio.gather(
        *[
            _update_one_device(
                device_key=device_key,
                device=device,
                config=config,
                context=context,
                node_id=node_id,
                nautobot_service=nautobot_service,
                credentials=credentials,
                update_service=update_service,
                parsed=parsed,
            )
            for device_key, device in device_items
        ]
    )

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}
    for device_key, updated_device, ok, _resolved_id in results:
        if updated_device is None:
            continue
        if ok:
            success_devices[device_key] = updated_device
        else:
            failed_devices[device_key] = updated_device

    logger.info(
        "%s finished success=%d failure=%d run_id=%s",
        _STEP_ID,
        len(success_devices),
        len(failed_devices),
        run.id,
    )

    return _build_outcomes(context, success_devices, failed_devices)
```

`execute()` drops from 245 lines to ~50; `_update_one_device` (the per-device closure, now a
module-level function taking explicit parameters instead of capturing 8 outer-scope variables) is the
largest remaining unit at ~100 lines. It's still over the 50-line guideline — a further split into
"resolve identifier → call update_service → shape the outcome" is legitimate optional follow-up, but not
done here, since the double dividend this plan is chasing (line count *and* testability) is already won:
`_parse_config`, `_resolve_device_items`, `_count_enabled_fields`, and `_build_outcomes` are now pure
functions with no I/O, directly unit-testable without mocking Nautobot at all — see Step 5.

**Everything else in the table above:** same procedure, no frozen diff (bodies will drift before this
plan is executed):

1. Read the full function body.
2. Identify the seam — config-parsing/validation → per-device (or per-item) work → outcome/response
   assembly is the recurring shape across every workflow-step executor in this codebase, and is exactly
   what `get_ise_tacacs_key/executor.py:138-284`'s `_tier_name_exact32` / `_tier_name_any` /
   `_tier_location_group` / `_tier_ip_prefix_scan` / `_tier_ip_range_scan` / `_find_tacacs_key` already
   demonstrate working end-to-end in this repo — read it first.
3. Extract each seam into a module-level `_snake_case` helper taking only the specific values it needs
   (not the whole `config`/`context` dict), as done above.
4. Add or extend `tests/unit/test_<step>_executor.py` with direct tests of the new pure helpers, not
   just end-to-end `execute()` tests.
5. Run `ruff check .` and that step's existing test file before moving to the next function.

### Verification

```bash
cd backend
ruff check .
python -m pytest -q tests/unit/test_update_nautobot_device_executor.py -v
python -m pytest -q   # full suite, must stay green
```

---

## Step 5: Testing Debt (§7) — Sustained Work, Refreshed Target List

**What:** A fresh coverage run this pass shows **54%** overall (was 53% in the original analysis — the
gap is essentially unchanged; two new 0%-covered files surfaced: `services/git/connection.py` and
`services/git/version_control_service.py`, alongside the ones already named):

| Area | Current coverage | File(s) |
|---|---|---|
| Git write path | 0–21% | `services/git/debug_service.py` (0%), `services/git/operations.py` (0%), `services/git/cache.py` (0%), `services/git/connection.py` (0%), `services/git/version_control_service.py` (0%), `services/git/file_service.py` (7%), `services/git/service.py` (21%) |
| Nautobot mutation path | 6–14% | `services/nautobot/devices/update.py` (7%), `devices/interface_workflow.py` (6%), `devices/creation.py` (14%), resolvers (`device_resolver.py` 7%, `metadata_resolver.py` 9%, `network_resolver.py` 12%) |
| Cache layer | 11% | `services/cache/redis_cache_service.py` |
| Source routers | 21–25% | `routers/sources/ise/ops.py` (25%), `routers/sources/nautobot/ops.py` (24%), `routers/sources/nautobot/crud.py` (21%) — Step 1 above touches `test_connection` in two of these three files; add a router-level permission test alongside that change rather than waiting for a separate pass |
| Under-tested executors | 14–16% | `update_nautobot_device` (15%), `merge_content` (16%), `filter_output` (14%) |
| Integration suite | **0 tests** | `tests/integration/` contains only a README |

**Why this cannot be "one patch":** unchanged reasoning from `FABLE_PRIO.md` Step 12 — closing a
27-point gap concentrated in git-write and Nautobot-mutation code is genuine, multi-day test-authoring
work against real external-system behavior (mocked at the httpx/subprocess boundary, not the service
boundary), not a mechanical fix.

**Worked example (concrete, not aspirational):** Step 4 just turned `update_nautobot_device/executor.py`
(previously 15% covered, and the reason it appears in both this table and Step 4's) into four pure,
directly-testable helpers. Here is the direct test coverage that decomposition unlocks — no Nautobot
mocking required for any of these:

### New test — `backend/tests/unit/test_update_nautobot_device_helpers.py`

```python
"""Direct unit tests for the pure helpers extracted from update_nautobot_device/executor.py
in doc/refactoring/FABLE_REST.md Step 4 — see doc/FABLE-ANALYSIS.md §5.2 and §7."""

from __future__ import annotations

import unittest

from models.workflow_context import WorkflowContext
from workflow_steps.update_nautobot_device.executor import (
    _build_outcomes,
    _count_enabled_fields,
    _parse_config,
    _resolve_device_items,
)


class ParseConfigTests(unittest.TestCase):
    def test_requires_source_id(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config({"update_fields": {"name": {"enabled": True, "value": "x"}}})

    def test_requires_at_least_one_enabled_field_or_interface(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config({"nautobot_source_id": "src-1", "update_fields": {}})

    def test_defaults_are_applied(self) -> None:
        parsed = _parse_config(
            {
                "nautobot_source_id": "src-1",
                "update_fields": {"name": {"enabled": True, "value": "new-name"}},
            }
        )
        self.assertEqual(parsed.source_id, "src-1")
        self.assertTrue(parsed.add_prefix)
        self.assertEqual(parsed.default_prefix_length, "/24")
        self.assertFalse(parsed.sync_interfaces)
        self.assertEqual(parsed.identifier_mode, "from_context")


class ResolveDeviceItemsTests(unittest.TestCase):
    def test_explicit_mode_yields_single_placeholder_item(self) -> None:
        items = _resolve_device_items("explicit", WorkflowContext(devices={}))
        self.assertEqual(items, [("explicit", None)])

    def test_from_context_requires_devices(self) -> None:
        with self.assertRaises(ValueError):
            _resolve_device_items("from_context", WorkflowContext(devices={}))


class CountEnabledFieldsTests(unittest.TestCase):
    def test_counts_top_level_and_custom_fields(self) -> None:
        count = _count_enabled_fields(
            {
                "name": {"enabled": True, "value": "x"},
                "location": {"enabled": False, "value": "y"},
                "custom_fields": {
                    "cf_a": {"enabled": True, "value": "1"},
                    "cf_b": {"enabled": True, "value": "2"},
                },
            }
        )
        self.assertEqual(count, 3)


class BuildOutcomesTests(unittest.TestCase):
    def test_omits_failure_outcome_when_nothing_failed(self) -> None:
        context = WorkflowContext(devices={})
        outcomes = _build_outcomes(context, success_devices={}, failed_devices={})
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "success")

    def test_includes_failure_outcome_when_something_failed(self) -> None:
        context = WorkflowContext(devices={})
        outcomes = _build_outcomes(context, success_devices={}, failed_devices={"dev-1": None})
        self.assertEqual([o.name for o in outcomes], ["success", "failure"])
```

(Adjust the `WorkflowContext`/device-fixture construction to match whatever helper the existing
`tests/unit/test_update_nautobot_device_executor.py` already uses for constructing contexts and
`DeviceContext` fixtures, to stay consistent with that file's conventions rather than inventing a second
style.)

**Recommended order** (highest risk first, matching `FABLE_PRIO.md` Step 12's own ordering — unchanged
by this refresh, since the risk ranking hasn't shifted):

1. **Git write path** — `debug_service.py`, `operations.py`, `cache.py`, and now also `connection.py`,
   `version_control_service.py` (both surfaced at 0% in this rescan). Start with `GitOperationsService`
   (backing `routers/git/operations.py`, itself only ~23% covered) since it's the primary write entry
   point.
2. **Nautobot mutation path** — `devices/update.py`, `devices/interface_workflow.py`,
   `devices/creation.py`, and the three resolvers. Mock at the `NautobotService` client boundary the
   same way `tests/unit/test_nautobot_resolve.py` and `tests/unit/test_nautobot_interfaces.py` already
   do for read paths.
3. **Integration suite** — stand up `tests/integration/` against a real PostgreSQL instance (the
   project's existing dev-environment Docker postgres/redis setup), closing the "integration" leg of
   `common/testing.md`'s unit+integration+E2E requirement — currently zero tests there.
4. **Under-tested executors** — `update_nautobot_device` (partially addressed by this step's worked
   example — the pure helpers are now covered; `_update_one_device` and `execute()` itself still need
   direct/integration-style coverage), `merge_content`, `filter_output`. Do these alongside Step 4's
   decomposition work for the remaining functions in that table — splitting inherently produces smaller,
   individually-testable units.
5. **`redis_cache_service.py`** — lowest priority; cache-miss behavior is already exercised indirectly,
   but the service deserves direct unit coverage for its Redis-specific serialization/TTL logic. (Note:
   Step 2 above adds a second, independent Redis-backed component — `LoginRateLimiter` — with its own
   dedicated test file, so this item is specifically about the *cache* service, not Redis usage in
   general.)
6. **Source routers** (`sources/ise/ops.py`, `sources/nautobot/ops.py`, `sources/nautobot/crud.py`) —
   Step 1 above changes permission/error-handling behavior on `test_connection` in two of these files;
   add a `require_permission`-style router test (see the pattern used by
   `tests/unit/test_require_permission_inactive_user.py` from `FABLE_PRIO.md` Step 4) confirming
   `test_connection` now 403s for a `read`-only user, while you're already in these files for Step 1.

### Verification (per new test file, not once at the end)

```bash
cd backend
python -m pytest -q --cov=. --cov-report=term-missing <target module>
python -m pytest -q
ruff check .
```
