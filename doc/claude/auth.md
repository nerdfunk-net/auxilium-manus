# Authentication & Authorization

## JWT Token Structure
```python
{
  "sub": "username",
  "user_id": 123,
  "iat": 1234567890,      # mint time (Unix seconds)
  "sid_iat": 1234567890,  # original login time; carried UNCHANGED through every refresh
  "jti": "…",             # random per-token id (minted, not yet consumed)
  "tv": 0,                # user.token_version at mint time
  "exp": 1234567890,      # clamped so it never outlives sid_iat + SESSION_MAX_AGE_HOURS
}
```
Permissions are **not** embedded in the JWT. Authorization is evaluated per-request
against the database via `RBACService.has_permission(user_id, resource, action)` — there
is no caching and no JWT permission claim to keep in sync.

**Revocation (`token_version`).** `users.token_version` is an int column embedded in every
access token as `tv`. Bumping it invalidates every outstanding token for that user. It is
bumped by: `AuthService.bump_token_version` (`POST /auth/logout`), `AuthService.change_password`
(self-service change — folded into the same write), and `UserService.update_user` /
`set_active` on an admin password change, username change, or deactivation.
`core/auth.py::_load_active_user` rejects a token whose `tv` mismatches the row (both sides
isinstance-guarded); `AuthService.refresh_access_token` is strict and additionally requires a
numeric `sid_iat`, so a pre-`tv` token cannot be refreshed. Legacy pre-`tv`/`sid_iat` tokens
die at their own `exp` (≤ 60 min) since they cannot be renewed.

**Absolute session lifetime (`SESSION_MAX_AGE_HOURS`, default 12, floor 1).** Measured from
`sid_iat`, which `create_access_token` preserves across refreshes. `_load_active_user` and
`refresh_access_token` both reject a session older than this regardless of per-token `exp`.
A successful `POST /auth/change-password` returns a fresh `SessionResponse` (new token,
`sid_iat = now`); `app/api/auth/change-password/route.ts` re-sets the auth cookie so the
forced-change flow does not bounce the user back to login.

**Login rate limiting (T1).** `POST /auth/login` uses two independent *failure* budgets:
per client IP (20 failures/60s) and per username (100 failures/15min); a success clears only
the username bucket. Client IP comes from `core/client_ip.py::resolve_client_host` —
honoured only when the direct peer is in `TRUSTED_PROXY_IPS` (IPs or CIDRs).
See `docker/DOCKER.md` "Client IP and login rate limiting".

## RBAC Data Model
Five tables in `/backend/core/models/rbac.py`: `roles`, `permissions`, `role_permissions`,
`user_roles`, `user_permissions`. `user_permissions` holds per-user overrides (explicit
allow or deny for one `resource:action`) that sit above role-derived grants.

Precedence: **user-level override (allow or deny) > role-derived grant > default-deny.**
See `backend/services/auth/rbac_service.py::RBACService.has_permission`.

## RBAC Grant Policy (P1–P8)

`RBACService` enforces a delegation-bound model (no privilege amplification):

| # | Rule |
|---|---|
| P1 | An actor may never change their own roles/overrides, or delete/deactivate themselves. |
| P2 | An actor may grant only permissions they currently hold. `admin` bypasses. |
| P3 | Any change touching `rbac.*`, `users`, `system.*`, or `secret_manager.*` requires `admin`. |
| P4 | Any change to a user who currently holds `admin` requires `admin`. |
| P5 | System roles (`is_system=True`) cannot be renamed, deleted, or have `is_system` changed. |
| P6 | The last **active** user holding `admin` cannot lose it (role removal, deactivation, deletion). Deactivated admins do not count. |
| P7 | Internal callers (seed, lifespan) pass `actor_user_id=None` and bypass P1–P4. |
| P8 | Password reset or username change of another user requires target's permissions to be a subset of the actor's with no protected permission (else requires `admin`). |

Every mutating `RBACService`/`UserService` method takes `actor_user_id: int | None`; routers
pass `current_user.id` and map `AccessDeniedError` → 403. See
`backend/services/auth/rbac_service.py` and `backend/services/users/user_service.py`.

## Permission Pattern
Format: `{resource}:{action}` (e.g., `users:read`, `settings:write`, `credentials:delete`)

## Backend Auth Dependencies
```python
from core.auth import verify_token, require_permission, require_role

# Basic auth
@router.get("/data")
async def get_data(user: dict = Depends(verify_token)):
    pass

# Permission required
@router.post("/users", dependencies=[Depends(require_permission("users", "write"))])
async def create_user():
    pass

@router.get("/workflows", dependencies=[Depends(require_permission("workflows", "read"))])
async def get_workflows():
    pass

# Role required
@router.delete("/critical")
async def delete_critical(user: dict = Depends(require_role("admin"))):
    pass
```

## Frontend Auth
```typescript
import { useAuthStore } from '@/lib/auth-store'
const user = useAuthStore(state => state.user)

// API calls always go through the Next.js proxy on the same origin.
fetch('/api/proxy/users')
```

**Proxy-only auth rule:** Browsers must never call the FastAPI backend directly.
Frontend requests go to `/api/proxy/*`; the Next.js server forwards them to `BACKEND_URL`
and attaches the HTTP-only auth cookie as a backend `Authorization` header.

## OIDC Identity Binding

An OIDC login is matched to a local user by `(oidc_provider, oidc_subject)` **only** —
never by username. `oidc_subject` stores the IdP's `sub` claim; `OIDCService.extract_user_data`
refuses a token without one. The pair has a unique partial index on `users`.

If an IdP-presented username collides with a row this identity isn't already bound to,
`provision_or_get_user` raises `OIDCIdentityConflictError` (403) — an IdP-controlled claim
must never be able to take over an existing local account. See
`backend/services/auth/oidc_service.py::provision_or_get_user`.

**Auth-request hardening.** Authorization requests carry a `nonce` and PKCE
(`code_challenge`/`code_challenge_method=S256`). `routers/oidc.py` stores
`{redirect_uri, nonce, code_verifier}` as the Redis state value; the callback verifies
`code_verifier` and `nonce` (constant-time compare; missing/mismatch → `OIDCError`).
`client_secret` resolves from `OIDC_<PROVIDER_ID>_CLIENT_SECRET` (provider id upper-cased,
non-alnum → `_`) with the YAML `client_secret` as fallback; an empty secret raises before
the HTTP call.

## Password Policy and Forced Change

`backend/services/auth/password_policy.py::validate_password` — 12–128 characters,
small common-password denylist, must not equal the username (NIST 800-63B style).
Enforced in `UserService.create_user`/`update_user` and `AuthService.change_password`;
Pydantic models mirror the length bounds for a fast 422. Outside development,
`core/production_guards.py` rejects a `SECRET_KEY` under 32 chars or an `INITIAL_PASSWORD`
below the policy minimum at startup.

Every user has `must_change_password: bool`. It is set on the seeded admin and whenever
an admin sets someone's password; cleared by a successful `POST /auth/change-password`
(rate-limited, keyed `change-password:<user_id>`). `core/auth.py::get_current_user` and
`_require_active_user_id` both 403 with `{"code": "password_change_required"}` when the
flag is `True` (checked via `is True`, so a test double never trips it accidentally). Only
`get_current_user_allow_password_change` — used by `/auth/me`, `/auth/change-password`, and
`/auth/refresh` — skips the check. Frontend: `useApi`'s `buildApiErrorMessage` recognizes
the 403 code and opens a forced, non-dismissable `ChangePasswordDialog` in `DashboardShell`.
