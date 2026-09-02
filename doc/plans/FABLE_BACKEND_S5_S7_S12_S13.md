# Plan: Fix S5, S7, S12, S13

Source: `doc/analysis/FABLE_BACKEND_20260902.md` §5.3 (and §4.3 for S7).
Status: **implemented** on branch `fix/fable-backend-s5-s7-s12-s13`
(S7 `cd709d4`, S12 `e1382fc`, S5 `d264af6` + `dcf30db` + `c304045`, S13 `bb80ef9`, docs `HEAD`).

| # | Sev | Issue | Clarity | Decision |
|---|---|---|---|---|
| S5 | M | No JWT revocation / absolute session lifetime | Clear | D1=(a), D2=12h |
| S7 | M | Git TLS/SSH `os.environ` cross-request leakage | Clear | none |
| S12 | L | `SECRET_KEY` / KDF settings hygiene | Partly fixed | none |
| S13 | L | OIDC missing `nonce` + PKCE; secret only on disk | Clear | D3 as recommended |

Every issue ends with the tests that must exist before the fix is considered done.

---

## 0. Decisions (resolved)

There is no deployed instance and a single user, so **backward compatibility with
pre-S5 tokens is a non-goal**. Enforcement split:

- `refresh_access_token` is **strict** — a token without a numeric `sid_iat` and an
  `int` `tv` matching the user cannot be refreshed. Every pre-S5 token dies at its
  first keepalive.
- `_load_active_user` (every normal authenticated request) enforces the checks
  **when they can be evaluated**: `tv` mismatch is rejected only when both the claim
  and `user.token_version` are `int` (a real DB row always is); `sid_iat` age is
  enforced only when the claim is a number (every token this code mints has it).
  A claim-less pre-S5 token is therefore *not* proactively 401'd on a plain GET — it
  just can't be renewed and expires at its own `exp` (≤ 60 min).

This isinstance-guarding is the same test-double tolerance the codebase already uses
for `must_change_password` (`is True`, not truthy — see CLAUDE.md), and it keeps the
~170 router unit tests that inject a minimal fake `verify_token` payload working. The
operator still logs in once after the S5 deploy (the old cookie's token can't
refresh). All grace / rolling-deploy handling is removed from §1.4 and §1.6.

**D1 — Logout invalidation strategy → (a) bump `token_version`.**

One integer on `User`; logout, password change, username change, and deactivation all
bump it. Every other live JWT for that user dies immediately. Simple, no Redis dependency
on the logout path. Accepted trade-off (single-user, so irrelevant in practice): logging
out of one browser ends every other session. The `jti` claim is still minted (cheap,
useful later) but nothing consumes it under (a).

**D2 — Absolute session lifetime → `SESSION_MAX_AGE_HOURS=12`.**

Independent of `ACCESS_TOKEN_EXPIRE_MINUTES` (sliding 60 min) and
`REFRESH_TOKEN_MAX_AGE_HOURS` (how stale an expired token may be when exchanged). A stolen
token that is refreshed every hour still dies 12 h after the original login. Carry the
original issue time as claim `sid_iat` through every refresh. A successful
`POST /auth/change-password` mints a fresh token with `sid_iat = now`, i.e. it resets the
absolute clock — deliberate, the user just re-proved the current password (see §1.8).

**D3 — OIDC `client_secret` env override naming.**

`OIDC_<PROVIDER_ID>_CLIENT_SECRET` (provider id uppercased, non-alnum → `_`).
Example: provider `corporate` → `OIDC_CORPORATE_CLIENT_SECRET`. Env wins over YAML when
set; YAML remains the fallback for local/dev. Only confidential clients are supported —
an empty resolved secret raises `OIDCError` before the token call (public-client /
secret-less PKCE is explicitly out of scope).

### S12 already partially done

`core/production_guards.py` already enforces `MIN_SECRET_KEY_LENGTH = 32` outside
development (shipped with the S4/S6 work). S12's remaining work is: move `KDF_ITERATIONS`
into `Settings`, cache the derived Fernet key once per process, and document the static
KDF salt.

---

## 1. S5 — JWT revocation and absolute session lifetime

### 1.1 Problem in one sentence

Logout only clears the HTTP-only cookie; the JWT stays valid until `exp`. Refresh will
re-issue a fresh 60-minute token from a token up to 24 h past expiry, so a stolen token
refreshed once a day lives forever. Password / username change and deactivation do not
invalidate existing tokens.

### 1.2 Data model

`backend/core/models/users.py` — before:

```python
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
```

after:

```python
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # Bumped on password/username change, deactivation, and logout. Embedded in every
    # JWT as claim `tv`; verify_token / refresh reject a mismatch.
    token_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
```

Auto-schema sync adds the column on next start (`doc/MIGRATION_SYSTEM.md`).

### 1.3 Settings

`backend/core/config.py` — add next to the existing token settings:

```python
    # in Settings attrs
    session_max_age_hours: int

    # in __init__, after refresh_token_max_age_hours
    self.session_max_age_hours = self._get_int("SESSION_MAX_AGE_HOURS", 12)
    self._validate_session_max_age()

    def _validate_session_max_age(self) -> None:
        if self.session_max_age_hours < 1:
            raise RuntimeError("SESSION_MAX_AGE_HOURS must be at least 1")
```

Document in `backend/.env.example`:

```bash
# Absolute session lifetime from original login (carried through refreshes as sid_iat)
# SESSION_MAX_AGE_HOURS=12
```

### 1.4 Token create / refresh

`backend/services/auth/auth_service.py` — before:

```python
    def create_access_token(self, user: User) -> tuple[str, int]:
        expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
        expires_at = datetime.now(UTC) + expires_delta
        payload = {
            "sub": user.username,
            "user_id": user.id,
            "exp": expires_at,
        }

        token = jwt.encode(payload, settings.secret_key, algorithm="HS256")

        return token, int(expires_delta.total_seconds())
```

after:

```python
    def create_access_token(
        self,
        user: User,
        *,
        sid_iat: datetime | None = None,
    ) -> tuple[str, int]:
        now = datetime.now(UTC)
        session_started = sid_iat or now
        # Absolute cap: refuse to mint a token whose session is already too old.
        if now - session_started > timedelta(hours=settings.session_max_age_hours):
            raise AuthenticationError("Invalid authentication token")

        expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
        # Also clamp exp so a token never outlives the absolute session.
        session_deadline = session_started + timedelta(hours=settings.session_max_age_hours)
        expires_at = min(now + expires_delta, session_deadline)

        payload = {
            "sub": user.username,
            "user_id": user.id,
            "iat": int(now.timestamp()),
            # original login; preserved verbatim across refreshes. Plain int so
            # create and _load_active_user / refresh read back the same type.
            "sid_iat": int(session_started.timestamp()),
            "jti": secrets.token_urlsafe(16),
            "tv": user.token_version,
            "exp": expires_at,
        }
        token = jwt.encode(payload, settings.secret_key, algorithm="HS256")
        return token, int((expires_at - now).total_seconds())
```

Add `import secrets` at the top of the file. `expires_at` stays a `datetime` — PyJWT
serialises `exp` to NumericDate itself and `verify_token` already relies on that.

`refresh_access_token` — before (excerpt):

```python
        user = self.users.get_by_id(user_id)
        if user is None or not user.is_active or user.username != username:
            raise AuthenticationError("Invalid authentication token")

        access_token, expires_in = self.create_access_token(user)
        return user, access_token, expires_in
```

after:

```python
        user = self.users.get_by_id(user_id)
        if user is None or not user.is_active or user.username != username:
            raise AuthenticationError("Invalid authentication token")

        token_version = payload.get("tv")
        if not isinstance(token_version, int) or token_version != user.token_version:
            raise AuthenticationError("Invalid authentication token")

        sid_iat_raw = payload.get("sid_iat")
        if not isinstance(sid_iat_raw, int | float):
            raise AuthenticationError("Invalid authentication token")
        sid_iat = datetime.fromtimestamp(sid_iat_raw, UTC)

        access_token, expires_in = self.create_access_token(user, sid_iat=sid_iat)
        return user, access_token, expires_in
```

Strict, matching §1.6: no `iat` fallback, no `tv` default. A token without `tv` /
`sid_iat` cannot be refreshed. PyJWT encodes `datetime` claims as NumericDate; on decode
`sid_iat` comes back as `int`, so `create_access_token` should write it as a plain Unix
timestamp (`int(session_started.timestamp())`) rather than a `datetime`, so create and
refresh round-trip the same shape.

### 1.5 Bump helpers and call sites

Add on `AuthService` (or `UserRepository` — service is better so routers stay thin):

```python
    def bump_token_version(self, user_id: int) -> None:
        user = self.users.get_by_id(user_id)
        if user is None:
            return
        self.users.update_user(user_id, token_version=user.token_version + 1)
```

Note: `UserRepository.update_user` currently skips `None` values via
`if value is not None`, so `token_version=0` would be skipped — but we only ever write
`current + 1`, so this is fine. Do **not** pass `token_version=0` through that path.

Call `bump_token_version` from:

| Event | Where |
|---|---|
| Self-service password change | `AuthService.change_password` — after successful hash update |
| Admin sets password | `UserService.update_user` when `password is not None` |
| Username change | `UserService.update_user` when `username is not None` |
| Deactivation | `UserService.update_user` when `is_active is False`, and `UserService.set_active(..., False)` |
| Logout | new `POST /auth/logout` (below) |

`change_password` — after:

```python
    def change_password(self, user: User, current_password: str, new_password: str) -> User:
        if not password_hash.verify(current_password, user.password_hash):
            raise AuthenticationError("Current password is incorrect")
        validate_password(new_password, username=user.username)
        updated = self.users.update_user(
            user.id,
            password_hash=password_hash.hash(new_password),
            must_change_password=False,
            token_version=user.token_version + 1,
        )
        return updated or user
```

`UserService.update_user` — fold the bump into the same write:

```python
        if username is not None:
            updates["username"] = username
        if password is not None:
            updates["password_hash"] = password_hash.hash(password)
            updates["must_change_password"] = True
        if is_active is not None:
            updates["is_active"] = is_active
        if updates and target is not None and (
            "password_hash" in updates or "username" in updates or updates.get("is_active") is False
        ):
            updates["token_version"] = target.token_version + 1
        return self._repo.update_user(user_id, **updates)
```

`set_active(False)` must bump too:

```python
    def set_active(
        self, user_id: int, is_active: bool, *, actor_user_id: int | None = None
    ) -> User | None:
        if not is_active:
            self._assert_can_remove(user_id, actor_user_id)
            target = self._repo.get_by_id(user_id)
            if target is None:
                return None
            return self._repo.update_user(
                user_id, is_active=False, token_version=target.token_version + 1
            )
        return self._repo.set_active(user_id, is_active)
```

### 1.6 Verify path

`token_version` / `sid_iat` checks belong where the user row is already loaded —
`_load_active_user` — not in bare `verify_token` (which has no DB).

`backend/core/auth.py` — `_load_active_user` before:

```python
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

    return user
```

after:

```python
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

    # Revocation (S5): `tv` = the user's token_version at mint time; a bump
    # (logout, password/username change, deactivation) makes older tokens stale.
    # isinstance-guarded on BOTH sides so a mocked user row with a non-int
    # token_version does not trip this — same tolerance as `must_change_password
    # is True` elsewhere in this module. A real DB row always has an int here.
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

    # Absolute session lifetime (S5): enforced whenever `sid_iat` is present
    # (every token this code mints has it). refresh_access_token additionally
    # *requires* it, so a claim-less pre-S5 token cannot be renewed and dies at
    # its own `exp`.
    sid_iat_raw = token_payload.get("sid_iat")
    if isinstance(sid_iat_raw, int | float):
        age = datetime.now(UTC) - datetime.fromtimestamp(sid_iat_raw, UTC)
        if age > timedelta(hours=settings.session_max_age_hours):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token",
                headers=AUTHENTICATE_HEADER,
            )

    return user
```

Add `from datetime import UTC, datetime, timedelta` to `core/auth.py`.

Legacy tokens: `_load_active_user` does not proactively 401 a claim-less pre-S5 token
(see §0 for why — test-double tolerance, and they cannot be refreshed anyway).
`refresh_access_token` (§1.4) *is* strict — it raises `AuthenticationError` when `tv`
or `sid_iat` is absent — so after the S5 deploy the operator's stale cookie fails its
first keepalive and they re-login once.

### 1.7 Logout endpoint

Backend currently has no local logout — only OIDC end-session and a Next.js cookie clear
(`frontend/src/app/api/auth/logout/route.ts`).

`backend/routers/auth.py` — add:

```python
@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    current_user: User = Depends(get_current_user_allow_password_change),
    db: Session = Depends(get_db),
) -> None:
    # allow_password_change: a forced-change user must still be able to sign out
    AuthService(db).bump_token_version(current_user.id)
```

Frontend `frontend/src/app/api/auth/logout/route.ts` — before:

```typescript
export async function POST() {
  const cookieStore = await cookies();
  clearAuthCookie(cookieStore);

  return NextResponse.json({ ok: true });
}
```

after:

```typescript
export async function POST(request: Request) {
  const cookieStore = await cookies();
  const token = cookieStore.get(AUTH_COOKIE_NAME)?.value;

  if (token) {
    // Best-effort server revoke; the cookie is cleared locally regardless.
    try {
      await proxyRequest({
        authorization: `Bearer ${token}`,
        path: ["api", "auth", "logout"],
        request,
      });
    } catch {
      // ignore — logout must never fail on the client
    }
  }

  clearAuthCookie(cookieStore);
  return NextResponse.json({ ok: true });
}
```

Add `import { proxyRequest } from "@/lib/api-proxy";` (and `AUTH_COOKIE_NAME` to the
existing `@/lib/auth` import). `POST()` gains a `request` param; the caller in
`auth-store.ts` already `fetch`es `/api/auth/logout` with no body, which is fine.

### 1.8 Change-password returns a fresh token

**Problem.** Once `AuthService.change_password` bumps `token_version` (§1.5), the
caller's current cookie token is dead on its next request. `POST /auth/change-password`
returns only `UserResponse`, so the user is silently logged out right after a successful
change — worst in the forced-change flow (log in → forced dialog → change → bounced to
login → log in again). Fix: the endpoint hands back a fresh token and the Next.js route
re-sets the cookie.

**Backend — `backend/routers/auth.py::change_password`.**

- `response_model=UserResponse` → `response_model=SessionResponse` (already defined in
  `models/auth.py` as `{access_token, token_type, expires_in, user}`).
- After the successful change, mint a token from the returned (refreshed) user:

```python
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
    access_token, expires_in = auth_service.create_access_token(user)  # sid_iat = now
    return SessionResponse(
        access_token=access_token,
        expires_in=expires_in,
        user=_build_user_response(user, db),
    )
```

`change_password` (§1.5) already returns the object refreshed by
`UserRepository.update_user`, so `user.token_version` is the new value and
`create_access_token` embeds the matching `tv`. `AuthService.change_password` itself is
unchanged beyond the §1.5 bump. No new Pydantic model.

**Frontend — new `frontend/src/app/api/auth/change-password/route.ts`** (mirror
`refresh/route.ts`, which already sets the auth cookie from a `SessionResponse`):

- read the cookie token → `401` if absent;
- `proxyRequest({ authorization: Bearer, path: ["api","auth","change-password"],
  body: await request.text(), request })`;
- `!ok`:
  - `400` → forward the backend `detail` string (policy message / "Current password is
    incorrect") so the dialog toast is useful — `refresh/route.ts` has no 400 branch,
    this route adds one;
  - `401` / `403` → `clearAuthCookie` + `401`;
  - else → `502`;
- ok → parse `{access_token, expires_in, user}` (reuse `parseAuthUser` +
  `refresh/route.ts`'s `parseSessionResponse` shape), `cookieStore.set(AUTH_COOKIE_NAME,
  access_token, { httpOnly, maxAge: expires_in, path: "/", sameSite: "lax", secure })`,
  return `{ user }`.

**Frontend — `frontend/src/hooks/queries/use-auth-mutations.ts`.** Replace the
`apiCall("auth/change-password")` call (which goes through the generic proxy and cannot
persist a cookie) with `fetch("/api/auth/change-password", { method: "POST",
body: JSON.stringify(data) })`, mirroring the refresh call in
`use-session-manager.ts`. On success parse `{ user }` and keep `setUser(user)` — that
already clears `must_change_password` in the store and dismisses the forced dialog. On
failure throw with the server message so the existing `onError` toast works.

`change-password-dialog.tsx` needs no change.

### 1.9 Tests (write first)

| Test | Asserts |
|---|---|
| `test_access_token_contains_iat_jti_tv_sid_iat` | claims present; `tv == user.token_version`; `sid_iat` is an int |
| `test_refresh_preserves_sid_iat` | refreshed token's `sid_iat` equals original |
| `test_refresh_rejects_when_session_max_age_exceeded` | `sid_iat` older than `SESSION_MAX_AGE_HOURS` → `AuthenticationError` |
| `test_refresh_rejects_stale_token_version` | bump version, refresh old token → error |
| `test_refresh_rejects_token_without_tv` | pre-S5 shape (`{sub,user_id,exp}`) → `AuthenticationError` |
| `test_refresh_rejects_token_without_sid_iat` | `tv` present but no `sid_iat` → `AuthenticationError` |
| `test_verify_rejects_stale_token_version` | `_load_active_user` with a real user row + stale `tv` claim → 401 |
| `test_verify_accepts_claimless_token_for_active_user` | pre-S5 shape + active user row → returns the user (not proactively 401'd; documents the §0 split) |
| `test_verify_rejects_session_older_than_max_age` | numeric `sid_iat` older than `SESSION_MAX_AGE_HOURS` → 401 |
| `test_change_password_returns_working_session` | response is `SessionResponse`; old token → 401, response's `access_token` → 200 on a protected route |
| `test_change_password_bumps_token_version` | `token_version` incremented by exactly 1 |
| `test_admin_password_reset_bumps_token_version` | same via `UserService.update_user` |
| `test_username_change_bumps_token_version` | same |
| `test_deactivation_bumps_token_version` | same via `update_user` and `set_active(False)` |
| `test_logout_bumps_token_version` | `POST /auth/logout` then reuse token → 401 |
| `test_create_access_token_clamps_exp_to_session_deadline` | near end of session, `expires_in` < full hour |

Extend `tests/unit/test_auth_refresh.py`; add `tests/unit/test_auth_token_version.py`.
Frontend: point the `useChangePasswordMutation` test at `/api/auth/change-password`;
`parseAuthUser` already covers the `user` payload.

---

## 2. S7 — Stop mutating `os.environ` in git code

### 2.1 Problem in one sentence

`set_ssl_env` and `GitAuthenticationService.setup_auth_environment` write
`GIT_SSL_NO_VERIFY` / `GIT_SSH_COMMAND` into process-global `os.environ`. Concurrent git
operations (web request threads, Hatchet worker slots) inherit each other's TLS/SSH
settings — a `verify_ssl=False` clone can disable verification for a concurrent
`verify_ssl=True` clone.

### 2.2 Current call shape

Every GitPython path nests the two context managers:

```python
# services/git/service.py (clone / pull / push / fetch — four sites)
with set_ssl_env(repository):
    with self._auth.setup_auth_environment(repository) as (
        clone_url, username, token, ssh_key_path,
    ):
        repo = Repo.clone_from(clone_url, target_path, branch=...)
        # or origin.pull / origin.push
```

`connection.py::_test_clone` already builds a private `env = os.environ.copy()` for
`subprocess.run`, but still enters `set_ssl_env` first, so the SSL mutation leaks to the
whole process for the duration of the test (and races with others).

GitPython 3.x already supports per-call env without touching `os.environ`:

- `Repo.clone_from(..., env=overrides)` — merged onto `os.environ.copy()` inside
  `Git.execute`
- `with repo.git.custom_environment(**overrides): ...` — same merge for pull/push/fetch

### 2.3 Replace `set_ssl_env` with a pure builder

`backend/services/git/env.py` — before:

```python
@contextmanager
def set_ssl_env(repository: dict):
    original = {
        "GIT_SSL_NO_VERIFY": os.environ.get("GIT_SSL_NO_VERIFY"),
        "GIT_SSL_CA_INFO": os.environ.get("GIT_SSL_CA_INFO"),
        "GIT_SSL_CERT": os.environ.get("GIT_SSL_CERT"),
    }
    try:
        if not repository.get("verify_ssl", True):
            ...
            os.environ["GIT_SSL_NO_VERIFY"] = "1"
        if repository.get("ssl_ca_info"):
            os.environ["GIT_SSL_CA_INFO"] = str(repository["ssl_ca_info"])
        if repository.get("ssl_cert"):
            os.environ["GIT_SSL_CERT"] = str(repository["ssl_cert"])
        yield
    finally:
        for key, val in original.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val
```

after:

```python
"""Per-call Git environment overrides. Never mutates os.environ."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from services.git.ssh_command import build_git_ssh_command

logger = logging.getLogger(__name__)

_GIT_ENV_KEYS = ("GIT_SSL_NO_VERIFY", "GIT_SSL_CA_INFO", "GIT_SSL_CERT", "GIT_SSH_COMMAND")


def build_git_env_overrides(
    repository: dict,
    *,
    ssh_key_path: str | None = None,
) -> dict[str, str]:
    """Return env overrides for one git subprocess.

    Callers pass the result to ``Repo.clone_from(..., env=...)``,
    ``repo.git.custom_environment(**...)``, or ``subprocess.run(..., env=merged)``.
    Nothing here writes to ``os.environ``.
    """
    overrides: dict[str, str] = {}

    if not repository.get("verify_ssl", True):
        host = "unknown"
        try:
            host = urlparse(repository.get("url") or "").hostname or "unknown"
        except ValueError:
            pass
        logger.warning("Git SSL verification disabled for repository url_host=%s", host)
        overrides["GIT_SSL_NO_VERIFY"] = "1"

    if repository.get("ssl_ca_info"):
        overrides["GIT_SSL_CA_INFO"] = str(repository["ssl_ca_info"])
    if repository.get("ssl_cert"):
        overrides["GIT_SSL_CERT"] = str(repository["ssl_cert"])

    if ssh_key_path:
        overrides["GIT_SSH_COMMAND"] = build_git_ssh_command(ssh_key_path)

    return overrides


def merge_git_environ(overrides: dict[str, str]) -> dict[str, str]:
    """Full environ for ``subprocess.run``. Clears prior GIT_* overrides first so a
    polluted parent env cannot enable ``GIT_SSL_NO_VERIFY`` on a verify_ssl=True repo.
    """
    import os

    env = os.environ.copy()
    for key in _GIT_ENV_KEYS:
        env.pop(key, None)
    env.update(overrides)
    return env
```

Delete the `set_ssl_env` context manager entirely. Update imports.

### 2.4 Stop mutating `GIT_SSH_COMMAND` in auth

`backend/services/git/auth.py::setup_auth_environment` — before (excerpt):

```python
        original_ssh_command = os.environ.get("GIT_SSH_COMMAND")

        try:
            if auth_type == "ssh_key" and ssh_key_path:
                os.environ["GIT_SSH_COMMAND"] = build_git_ssh_command(ssh_key_path)
                ...
                yield original_url, username, token, ssh_key_path
            else:
                ...
                yield clone_url, username, token, ssh_key_path
        finally:
            if original_ssh_command is not None:
                os.environ["GIT_SSH_COMMAND"] = original_ssh_command
            elif "GIT_SSH_COMMAND" in os.environ:
                del os.environ["GIT_SSH_COMMAND"]
```

after:

```python
        try:
            if auth_type == "ssh_key" and ssh_key_path:
                logger.info(
                    "Using SSH key authentication for repository '%s'",
                    repository.get("name"),
                )
                yield original_url, username, token, ssh_key_path
            else:
                clone_url = original_url
                parsed = urlparse(original_url) if original_url else None
                if parsed and parsed.scheme in ["http", "https"] and token:
                    clone_url = self.build_auth_url(original_url, username, token)
                    logger.info(
                        "Using token authentication for repository '%s'",
                        repository.get("name"),
                    )
                else:
                    logger.info(
                        "Using no authentication for repository '%s'",
                        repository.get("name"),
                    )
                yield clone_url, username, token, ssh_key_path
        finally:
            pass  # no process-global state to restore
```

Remove the unused `os` / `build_git_ssh_command` imports from this method's path if nothing
else in the file needs them (`build_git_ssh_command` moves to being called only from
`build_git_env_overrides`). Keep `resolve_credentials` / `build_auth_url` unchanged.

### 2.5 Call-site pattern in `GitService`

before:

```python
            with set_ssl_env(repository):
                with self._auth.setup_auth_environment(repository) as (
                    clone_url,
                    username,
                    token,
                    ssh_key_path,
                ):
                    repo = Repo.clone_from(
                        clone_url,
                        target_path,
                        branch=repository.get("branch", "main"),
                    )
```

after:

```python
            with self._auth.setup_auth_environment(repository) as (
                clone_url,
                username,
                token,
                ssh_key_path,
            ):
                overrides = build_git_env_overrides(
                    repository, ssh_key_path=ssh_key_path
                )
                repo = Repo.clone_from(
                    clone_url,
                    target_path,
                    branch=repository.get("branch", "main"),
                    env=overrides,
                )
```

Pull / push / fetch — after:

```python
            with self._auth.setup_auth_environment(repository) as (
                auth_url,
                username,
                token,
                ssh_key_path,
            ):
                overrides = build_git_env_overrides(
                    repository, ssh_key_path=ssh_key_path
                )
                origin = repo.remotes.origin
                original_url = None
                try:
                    if token and not ssh_key_path:
                        original_url = list(origin.urls)[0]
                        origin.set_url(auth_url)

                    with repo.git.custom_environment(**overrides):
                        origin.pull(branch)  # or origin.push(...)
                finally:
                    if original_url:
                        try:
                            origin.set_url(original_url)
                        except Exception:
                            pass
```

Apply the same pattern in `services/git/debug_service.py` (one site at ~308).

### 2.6 Connection test

`connection.py` — before:

```python
                with set_ssl_env(temp_repo):
                    return self._test_clone(
                        clone_url=clone_url,
                        ...
                        ssh_key_path=ssh_key_path,
                        test_request=test_request,
                    )
```

and inside `_test_clone`:

```python
        env = os.environ.copy()
        if auth_type == "ssh_key" and ssh_key_path:
            env["GIT_SSH_COMMAND"] = build_git_ssh_command(ssh_key_path)
```

after: drop the `set_ssl_env` wrapper; build overrides once and merge:

```python
                overrides = build_git_env_overrides(
                    temp_repo,
                    ssh_key_path=ssh_key_path if auth_type == "ssh_key" else None,
                )
                return self._test_clone(
                    clone_url=clone_url,
                    branch=test_request.branch,
                    test_path=test_path,
                    auth_type=auth_type,
                    env=merge_git_environ(overrides),
                    test_request=test_request,
                )
```

```python
    def _test_clone(..., env: dict[str, str], ...):
        ...
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
```

### 2.7 Tests (write first)

Replace `tests/unit/test_git_misc_helpers.py` SSL tests that assert `os.environ` mutation
(they `import set_ssl_env`, which is gone). Also rewrite the four
`tests/unit/test_git_connection_service.py` tests that `@patch("services.git.connection.set_ssl_env")`
— that patch target no longer exists; they should instead assert `_test_clone` is called
with an `env` dict built from `build_git_env_overrides` and that `os.environ` is untouched.

| Test | Asserts |
|---|---|
| `test_build_git_env_overrides_sets_no_verify` | `verify_ssl=False` → overrides contain `GIT_SSL_NO_VERIFY=1`; `os.environ` unchanged |
| `test_build_git_env_overrides_omits_no_verify_when_enabled` | `verify_ssl=True` → key absent |
| `test_build_git_env_overrides_includes_ssh_command` | `ssh_key_path` → `GIT_SSH_COMMAND` present |
| `test_merge_git_environ_clears_parent_pollution` | parent `os.environ` has `GIT_SSL_NO_VERIFY=1`; merge for `verify_ssl=True` yields env **without** that key |
| `test_setup_auth_environment_does_not_touch_os_environ` | enter/exit with ssh_key auth; `GIT_SSH_COMMAND` not in `os.environ` |
| `test_clone_passes_env_to_clone_from` | mock `Repo.clone_from`; assert `env=` kwarg equals overrides (patch at `services.git.service.Repo`) |

Optional concurrency smoke (not required for green CI): two threads, one `verify_ssl=False`
and one `True`, both calling `build_git_env_overrides` + a fake subprocess; assert the
True-path argv env never contains `GIT_SSL_NO_VERIFY`.

---

## 3. S12 — Secret / KDF hygiene

### 3.1 Problem in one sentence

`KDF_ITERATIONS` is read from raw `os.getenv` in `core/crypto.py` instead of `Settings`;
the Fernet key is re-derived (100 000 PBKDF2 iterations) on every `EncryptionService()`
construction (every credentials request); the static KDF salt is undocumented. The
`SECRET_KEY` ≥ 32 check from the analysis is **already shipped** in
`production_guards.py` — do not re-implement it.

### 3.2 Settings

`backend/core/config.py` — add:

```python
    kdf_iterations: int

    # in __init__
    self.kdf_iterations = self._get_int("KDF_ITERATIONS", 100_000)
    if self.kdf_iterations < 100_000:
        raise RuntimeError("KDF_ITERATIONS must be at least 100000")
```

Keep the existing `.env.example` comment (`# KDF_ITERATIONS=100000`).

### 3.3 Crypto module

`backend/core/crypto.py` — before:

```python
_KDF_SALT = b"auxilium-credential-encryption-v1"
_KDF_ITERATIONS = int(os.getenv("KDF_ITERATIONS", "100000"))


def _build_key(secret: str, iterations: int = _KDF_ITERATIONS) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_KDF_SALT,
        iterations=iterations,
    )
    return base64.urlsafe_b64encode(kdf.derive(secret.encode("utf-8")))
...
class EncryptionService:
    def __init__(self, secret_key: str | None = None) -> None:
        secret = secret_key or resolve_credential_secret()
        self._fernet = Fernet(_build_key(secret))
```

after:

```python
"""Symmetric encryption for credentials at rest.

Key derivation uses PBKDF2-HMAC-SHA256 with a **static** salt
(``_KDF_SALT``). A static salt is acceptable here because the input secret
(``CREDENTIAL_ENCRYPTION_KEY``) is a high-entropy random value, not a user
password — the KDF's job is key-stretching and domain separation from
``SECRET_KEY``, not protection against a low-entropy dictionary attack.
Rotating the salt would invalidate every ciphertext; treat a salt change as
a deliberate migration that re-encrypts the credentials table.
"""

from __future__ import annotations

import base64
import functools
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_KDF_SALT = b"auxilium-credential-encryption-v1"


def _iterations() -> int:
    # Late import avoids the config ↔ crypto cycle at module load.
    from core.config import settings

    return settings.kdf_iterations


@functools.lru_cache(maxsize=4)
def _build_key(secret: str, iterations: int) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_KDF_SALT,
        iterations=iterations,
    )
    return base64.urlsafe_b64encode(kdf.derive(secret.encode("utf-8")))


def resolve_credential_secret(explicit: str | None = None) -> str:
    secret = explicit or os.getenv("CREDENTIAL_ENCRYPTION_KEY") or os.getenv("SECRET_KEY")
    if not secret:
        raise RuntimeError(
            "No credential encryption secret available. Set CREDENTIAL_ENCRYPTION_KEY "
            "or SECRET_KEY."
        )
    return secret


class EncryptionService:
    def __init__(self, secret_key: str | None = None) -> None:
        secret = secret_key or resolve_credential_secret()
        self._fernet = Fernet(_build_key(secret, _iterations()))
```

`maxsize=4` covers the process default plus a few test secrets without unbounded growth.
Unit tests that construct `EncryptionService("test-secret-...")` keep working; they just
cache per distinct `(secret, iterations)` pair.

Also add a short paragraph to `doc/SECURITY-NOTES.md` under a new heading
"Credential encryption KDF salt" that restates the docstring rationale (so the next
reviewer does not re-open it).

### 3.4 Tests

| Test | Asserts |
|---|---|
| `test_build_key_is_cached` | two `_build_key(secret, iters)` calls return same object / `_build_key.cache_info().hits >= 1` |
| `test_kdf_iterations_come_from_settings` | monkeypatch `settings.kdf_iterations`; derived key differs from default-iteration key |
| `test_kdf_iterations_floor` | constructing `Settings` with `KDF_ITERATIONS=99999` raises `RuntimeError` |
| existing encrypt/decrypt tests | still pass unchanged |

---

## 4. S13 — OIDC `nonce`, PKCE, and env-based client secret

### 4.1 Problem in one sentence

The authorization request has no `nonce` (so the ID token is not bound to the browser
session that started login) and no PKCE (so a stolen auth code is enough if the token
endpoint is reachable). `client_secret` lives only in `config/oidc_providers.yaml` on
disk.

### 4.2 State payload in Redis

Today the login route stores a bare redirect URI string:

```python
# routers/oidc.py
cache.set(
    f"oidc-state:{state_with_provider}", redirect_uri, ttl_seconds=OIDC_STATE_TTL_SECONDS
)
...
stored_redirect_uri = cache.get(state_key)  # str
```

Change the cached value to a dict (RedisCacheService already JSON-serializes):

```python
cache.set(
    f"oidc-state:{state_with_provider}",
    {
        "redirect_uri": redirect_uri,
        "nonce": nonce,
        "code_verifier": code_verifier,
    },
    ttl_seconds=OIDC_STATE_TTL_SECONDS,
)
```

Callback reads:

```python
stored = cache.get(state_key)
if not isinstance(stored, dict) or "redirect_uri" not in stored:
    raise HTTPException(status_code=400, detail="Invalid state")
cache.delete(state_key)
redirect_uri_from_state = stored["redirect_uri"]
nonce = stored["nonce"]
code_verifier = stored["code_verifier"]
```

### 4.3 Service: generate PKCE + nonce, plumb through authorize / token / verify

`backend/services/auth/oidc_service.py`.

Add helpers:

```python
import hashlib
import base64

def generate_nonce(self) -> str:
    return secrets.token_urlsafe(32)

def generate_pkce_pair(self) -> tuple[str, str]:
    """Return (code_verifier, code_challenge) using S256."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge
```

`generate_authorization_url` — before:

```python
        params = {
            "client_id": client_id or provider["client_id"],
            "response_type": response_type,
            "scope": " ".join(scopes or provider.get("scopes") or DEFAULT_SCOPES),
            "redirect_uri": redirect_uri,
            "state": state,
        }

        return str(httpx.URL(config.authorization_endpoint).copy_with(params=params))
```

after:

```python
    async def generate_authorization_url(
        self,
        provider_id: str,
        redirect_uri: str,
        state: str,
        *,
        scopes: list[str] | None = None,
        response_type: str = "code",
        client_id: str | None = None,
        nonce: str,
        code_challenge: str,
    ) -> str:
        provider = self._get_provider_config(provider_id)
        config = await self.get_oidc_config(provider_id)

        params = {
            "client_id": client_id or provider["client_id"],
            "response_type": response_type,
            "scope": " ".join(scopes or provider.get("scopes") or DEFAULT_SCOPES),
            "redirect_uri": redirect_uri,
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }

        return str(httpx.URL(config.authorization_endpoint).copy_with(params=params))
```

`exchange_code_for_tokens` — before:

```python
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": provider["client_id"],
            "client_secret": provider["client_secret"],
        }
```

after:

```python
    async def exchange_code_for_tokens(
        self,
        provider_id: str,
        code: str,
        redirect_uri: str,
        *,
        code_verifier: str,
    ) -> dict[str, Any]:
        provider = self._get_provider_config(provider_id)
        config = await self.get_oidc_config(provider_id)
        ssl_context = self._get_ssl_context(provider_id)

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": provider["client_id"],
            "client_secret": self._client_secret(provider_id, provider),
            "code_verifier": code_verifier,
        }
        ...
```

`verify_id_token` — before:

```python
            claims = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=ID_TOKEN_ALGORITHMS,
                audience=provider["client_id"],
                issuer=config.issuer,
            )
```

after:

```python
    async def verify_id_token(
        self,
        provider_id: str,
        id_token: str,
        *,
        nonce: str,
    ) -> dict[str, Any]:
        ...
            claims = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=ID_TOKEN_ALGORITHMS,
                audience=provider["client_id"],
                issuer=config.issuer,
            )
        except jwt.InvalidTokenError as exc:
            raise OIDCError(f"Invalid ID token from provider '{provider_id}'") from exc

        token_nonce = claims.get("nonce")
        if not isinstance(token_nonce, str) or not token_nonce or token_nonce != nonce:
            raise OIDCError(f"Invalid ID token from provider '{provider_id}'")

        return claims
```

### 4.4 Client secret from env

Still in `oidc_service.py` (or `oidc_config_service.py` — service is fine so the YAML
reader stays a pure file loader):

```python
def _client_secret(self, provider_id: str, provider: dict[str, Any]) -> str:
    # provider_id is passed explicitly — the raw provider dict from
    # OidcConfigService.get_provider() is not guaranteed to carry a
    # "provider_id" key.
    env_key = "OIDC_" + "".join(
        ch.upper() if ch.isalnum() else "_" for ch in provider_id
    ) + "_CLIENT_SECRET"
    # Collapse duplicate underscores from non-alnum runs
    while "__" in env_key:
        env_key = env_key.replace("__", "_")
    return os.environ.get(env_key) or provider.get("client_secret") or ""
```

Call it as `self._client_secret(provider_id, provider)` from `exchange_code_for_tokens`.
If the resolved secret is empty, raise `OIDCError` before the HTTP call — only
confidential clients are supported (see §0, D3); secret-less public-client PKCE is out
of scope. This is not a regression: today `provider["client_secret"]` would `KeyError`
if absent, so a secret was already effectively required.

Update `config/oidc_providers.yaml.example`:

```yaml
    # client_secret: OAuth 2.0 confidential client secret.
    # Prefer setting OIDC_<PROVIDER_ID>_CLIENT_SECRET in the environment (e.g.
    # OIDC_CORPORATE_CLIENT_SECRET) so the secret is not on disk. YAML value is
    # the fallback for local development.
    client_secret: "your-client-secret-here"
```

### 4.5 Router wiring

`_build_login_response` — after:

```python
        state = oidc_service.generate_state()
        state_with_provider = f"{provider_id}:{state}"
        nonce = oidc_service.generate_nonce()
        code_verifier, code_challenge = oidc_service.generate_pkce_pair()
        authorization_url = await oidc_service.generate_authorization_url(
            provider_id,
            redirect_uri,
            state_with_provider,
            scopes=scopes,
            response_type=response_type,
            client_id=client_id,
            nonce=nonce,
            code_challenge=code_challenge,
        )
        cache.set(
            f"oidc-state:{state_with_provider}",
            {
                "redirect_uri": redirect_uri,
                "nonce": nonce,
                "code_verifier": code_verifier,
            },
            ttl_seconds=OIDC_STATE_TTL_SECONDS,
        )
```

`handle_callback` — after exchanging / verifying:

```python
        tokens = await oidc_service.exchange_code_for_tokens(
            provider_id, body.code, redirect_uri, code_verifier=stored["code_verifier"]
        )
        ...
        claims = await oidc_service.verify_id_token(
            provider_id, id_token, nonce=stored["nonce"]
        )
```

Update `tests/unit/test_oidc_router.py` fixtures: the fake cache must store the dict
shape, and the mocked `generate_authorization_url` / `exchange_code_for_tokens` /
`verify_id_token` signatures must accept the new kwargs.

### 4.6 Tests (write first)

| Test | Asserts |
|---|---|
| `test_generate_pkce_pair_s256` | challenge == base64url(SHA256(verifier)) without padding |
| `test_authorization_url_includes_nonce_and_pkce` | URL query has `nonce`, `code_challenge`, `code_challenge_method=S256` |
| `test_exchange_sends_code_verifier` | httpx mock received `code_verifier` in form body |
| `test_verify_id_token_rejects_wrong_nonce` | claims.nonce mismatch → `OIDCError` |
| `test_verify_id_token_rejects_missing_nonce` | no nonce claim → `OIDCError` |
| `test_client_secret_env_overrides_yaml` | env set → POST body uses env value, not YAML |
| `test_client_secret_empty_raises_before_http` | no env, no YAML secret → `OIDCError`, no token request made |
| `test_login_stores_nonce_and_verifier_in_cache` | cache value is dict with both keys |
| `test_callback_rejects_legacy_string_state` | cache holds a bare string → 400 |

Also update `tests/unit/test_oidc_service.py` for the new required kwargs on
`generate_authorization_url` / `exchange_code_for_tokens` / `verify_id_token` and the
`_client_secret(provider_id, provider)` signature.

---

## 5. Order of work and effort

| Step | Depends on | Effort |
|---|---|---|
| S7 Git env isolation (incl. `test_git_connection_service.py` rewrite) | none | 0.5 day |
| S12 KDF / Settings / cache / docs | none | 0.25 day |
| S5 `token_version` + claims + strict refresh/verify | none | 1 day |
| S5 logout endpoint + frontend cookie route | S5 token_version | 0.25 day |
| S5 change-password → fresh token (backend + new Next.js route + mutation) | S5 token_version | 0.25 day |
| S13 nonce + PKCE + env secret | none | 0.5–1 day |
| Docs: CLAUDE.md JWT claims blurb, SECURITY-NOTES KDF, `.env.example` | all | 0.25 day |

S7 and S12 are independent and can land first (small, low risk). S5 before S13 is
unrelated except both touch auth tests — do S5 first so refresh tests are stable before
OIDC router fixtures change. Decisions D1/D2/D3 are resolved (§0), so no step is blocked
on a decision.

---

## 6. Definition of done

- [x] All tests listed in §1.9, §2.7, §3.4, §4.6 exist and pass; coverage ratchet still
      ≥ 81 %.
- [x] `ruff check` clean on touched files; the four `scripts/check_*.py` guards pass.
- [x] Grep confirms **zero** assignments to `os.environ["GIT_SSL_*"]` or
      `os.environ["GIT_SSH_COMMAND"]` under `backend/services/git/`; `set_ssl_env` is
      deleted and has no remaining importers.
- [x] `EncryptionService()` construction in a tight loop does not re-run PBKDF2
      (cache hit); `KDF_ITERATIONS` is read only via `settings`.
- [x] A pre-S5 token (`{sub,user_id,exp}` only) returns 401 on the next authenticated
      request and cannot be refreshed. A token minted before a password change / logout
      returns 401. Refresh of a session older than `SESSION_MAX_AGE_HOURS` fails.
- [x] `POST /auth/change-password` returns a `SessionResponse`; the old token is dead
      and the returned token works. The Next.js `change-password` route re-sets the
      auth cookie, so the forced-change flow does not bounce the user to login.
- [x] OIDC authorization URL contains `nonce` + PKCE; callback rejects a wrong nonce;
      `OIDC_<ID>_CLIENT_SECRET` overrides YAML; an empty resolved secret raises before
      the token request.
- [x] `doc/analysis/FABLE_BACKEND_20260902.md` §5.3 rows S5, S7, S12, S13 updated to
      "fixed" with commit hashes once merged.
- [x] CLAUDE.md "Authentication & Authorization" documents: JWT claims
      (`iat`/`jti`/`tv`/`sid_iat`), `token_version` bump events (incl. change-password
      re-issue), `SESSION_MAX_AGE_HOURS`, and OIDC nonce/PKCE/env-secret.
