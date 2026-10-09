# Plan: Fix every open finding from `FABLE_MERGE_20261009.md`

Source: `doc/analysis/FABLE_MERGE_20261009.md` (merge of `FABLE_BACKEND_20260902/0912/0916`).
Status: **in progress** — Phases 1 (T3 deferred), 2 and 3 implemented, committed and reviewed
(`FABLE_MERGE_P1_P3_REVIEW.md`); Phases 4, 5 and 6 implemented (uncommitted; §4.5 Infisical live
verification still to be run); Phases 7–10 open.

Each phase is independent: it can be implemented, tested and committed on its own, in any
order. Where two phases touch the same file it is called out under **Depends on / conflicts**
(merge conflicts only, never a functional dependency; inside Phase 9, §9.6 needs §9.5 and §9.10 needs §9.5).
Run everything from `backend/` with the project venv (`source ../.venv/bin/activate`).
Write the tests first (RED), then the change (GREEN), as in the earlier FABLE plans.

"Before" blocks quote the code as it is on `main` (`4cc19a0`) on 2026-10-09. Line numbers
are indicative; search for the quoted text.

| Phase | Theme | Issues | Impact | Effort | Migration |
|---|---|---|---|---|---|
| 1 | Account and RBAC guards | T2, R3, R4, R5, T3, T4 | Medium → Low | S | no |
| 2 | Webhook and git-lock correctness | W1, W2, W3, W4 | Medium → Low | S | no |
| 3 | OpenBao hardening | V5–V14, plus SM6 and SM7 (same patterns) | Medium → Low | M | no |
| 4 | Secret Manager steps | SM5, SM8, SM9, SM11, Infisical verification | Medium → Low | M | no |
| 5 | Batfish robustness | B3 (cap), B4, B5, B6, B7, B8 | Medium → Low | M | no |
| 6 | Generic per-user rate limiting | S9, SM10, B3 (limit) | Medium | M | no |
| 7 | Secret redaction and upload bounds | W6, W5/S15 | Medium → Low | M | no |
| 8 | Inventory ownership | S14 / R6 | Medium | S | no |
| 9 | Code-quality hygiene | Q1–Q10, R7, T6, CI decision | Low | L | no |
| 10 | Docs and repository hygiene | D1–D7, T5 | Medium → Low | S | no |

Suggested order: 1, 2, 10 (cheap, closes the Medium items) → 3, 4, 5 → 6 → 7 → 8 → 9.

---

## 0. Decisions (defaults — change before starting a phase if you disagree)

**Confirmed 2026-10-09:** PD1 (block for everyone, as written), PD2 (as written, defer if > ~40 tests break),
PD8 (rename/delete handling; the FK variant is recorded in `doc/OPEN_TODOS.md`), CI (restore, §9.12).
All other PDs are still defaults.

Named `PD1…PD9` (plan decisions) so they are not confused with the documentation findings `D1…D7`.

**PD1 — Self-service credential changes (T2).** A user may never change their own password or
username through `PUT /users/{id}`, admins included; self-service is `POST /auth/change-password`.
Renaming yourself is not supported at all (an admin renames you). Consequence: the admin
user-edit dialog must not send `password`/`username` for the logged-in admin's own row — verify in
`settings/permissions/dialogs/user-dialog.tsx` when implementing Phase 1.

**PD2 — Mandatory token claims (T3).** `tv` and `sid_iat` become required on every authenticated
request. Test doubles that inject a minimal `verify_token` payload get a shared helper (§1.5).
If the number of failing tests after the change is unreasonably large (> ~40), land T3 alone
last in Phase 1 and defer it; nothing else in the phase depends on it.

**PD3 — `REFRESH_TOKEN_MAX_AGE_HOURS` (T4).** Keep the setting, change its default from 24 to 12
(equal to the session cap) and refuse a value above `SESSION_MAX_AGE_HOURS`. `backend/.env.example`
is updated. Anyone who set 24 explicitly gets a clear startup error.

**PD4 — Git lock timeout (W4).** Timeout becomes a hard failure (`RuntimeError`, classified by the
step runner as an execution failure). "Redis not configured" stays fail-soft with a WARNING.

**PD5 — Webhook budget (W1).** 60 deliveries / 60 s per repository **and** client IP, separate
limiter instance with its own Redis key prefix.

**PD6 — OpenBao management client in workers (V5).** Workers start the runtime client only (no
management login, token or renew loop). `production_guards` is left unchanged: the management
AppRole material is still required in the deployment environment; keeping it out of the worker
containers is a deployment choice noted in `doc/VAULT_INTEGRATION.md`.

**PD7 — Rate limits (S9).** Per-user Redis sliding window via a reusable FastAPI dependency
`rate_limited("<bucket>", attempts=..., window_seconds=...)`. Unlike login it falls back to an in-process
window when Redis is down (throttling must not stop operators). Budgets are in Phase 6.

**PD8 — Inventory ownership (S14).** Revised after reading the code: no `owner_user_id` migration.
Private inventories are carried along on user rename and removed on user delete, in the same
transaction; existing orphans only produce a startup warning (Phase 8). The FK variant is a separate,
larger plan if you want it.

**PD9 — Quality sweep scope (Q1).** Phase 9 fixes the structural items (Q2–Q10) completely and
Q1 (long functions) only for the five worst offenders. Further splits ride along when files are touched.

---

## Phase 1 — Account and RBAC guards (T2, R3, R4, R5, T3, T4)

Files: `services/users/user_service.py`, `services/auth/rbac_service.py`,
`routers/rbac/roles.py`, `core/auth.py`, `core/config.py`, `backend/.env.example`.
Depends on / conflicts: Phase 8 also edits `user_service.py` (rename handling) — land Phase 1 first.

### 1.1 T2 — no self password/username change through `PUT /users/{id}`

`backend/services/users/user_service.py::update_user`

before:
```python
        self._rbac.may_touch_target(actor_user_id, user_id)
        if is_active is False:
            self._assert_can_remove(user_id, actor_user_id)
        if password is not None or username is not None:
            # A password reset is an account takeover; a rename is an identity
            # change. Both are bounded by the target's effective rights (R1).
            self._rbac.assert_may_take_over(actor_user_id, user_id)
```

after:
```python
        self._rbac.may_touch_target(actor_user_id, user_id)
        if is_active is False:
            self._assert_can_remove(user_id, actor_user_id)
        if password is not None or username is not None:
            # T2: bypassing the current-password check of /auth/change-password
            # through this admin endpoint is not allowed, for anyone.
            if actor_user_id is not None and actor_user_id == user_id:
                raise AccessDeniedError(
                    "You cannot change your own password or username here; "
                    "use the change-password dialog"
                )
            # A password reset is an account takeover; a rename is an identity
            # change. Both are bounded by the target's effective rights (R1).
            self._rbac.assert_may_take_over(actor_user_id, user_id)
```

`backend/services/auth/rbac_service.py::assert_may_take_over` — the docstring promises the opposite.

before:
```python
        (P3). Self-changes are not blocked here (that is T2, out of scope);
        admins and internal callers (actor_user_id=None) bypass, like every
        other policy helper."""
```

after:
```python
        (P3). Self-changes are rejected earlier, in ``UserService.update_user``
        (T2); admins and internal callers (actor_user_id=None) bypass, like
        every other policy helper."""
```

### 1.2 R3 — reactivation honours P4

`backend/services/users/user_service.py::set_active`

before:
```python
            return self._repo.update_user(
                user_id, is_active=False, token_version=target.token_version + 1
            )
        return self._repo.set_active(user_id, is_active)
```

after:
```python
            return self._repo.update_user(
                user_id, is_active=False, token_version=target.token_version + 1
            )
        # R3 / P4: only an admin may bring a deactivated administrator back.
        # Approving a pending OIDC user (a non-admin target) still passes.
        self._rbac.may_touch_target(actor_user_id, user_id)
        return self._repo.set_active(user_id, is_active)
```

### 1.3 R4 — seeded catalog permissions cannot be deleted

`backend/services/auth/rbac_service.py` (add `ConflictError` to the existing import line
`from core.domain_exceptions import AccessDeniedError`)

before:
```python
    def delete_permission(self, permission_id: int) -> bool:
        return self._repo.delete_permission(permission_id)
```

after:
```python
    def delete_permission(self, permission_id: int) -> bool:
        permission = self._repo.get_permission_by_id(permission_id)
        if permission is not None:
            # Lazy import: rbac_seed imports the repository layer and lazily this module.
            from services.auth.rbac_seed import DEFAULT_PERMISSIONS

            if (permission.resource, permission.action) in {
                (resource, action) for resource, action, _ in DEFAULT_PERMISSIONS
            }:
                # R4: deleting it would cascade out of every role, admin included,
                # until the next restart re-seeds it.
                raise ConflictError("Built-in permissions cannot be deleted")
        return self._repo.delete_permission(permission_id)
```
(`ConflictError` is a `DomainError` → the global handler returns 409; no router change.)

### 1.4 R5 — deleting a role held by an administrator needs admin

`backend/services/auth/rbac_service.py`

before:
```python
    def delete_role(self, role_id: int) -> bool:
        return self._repo.delete_role(role_id)
```

after:
```python
    def delete_role(self, role_id: int, *, actor_user_id: int | None = None) -> bool:
        # R5 / P4: stripping a role from an administrator is a change to an administrator.
        if actor_user_id is not None and not self._is_admin(actor_user_id):
            if any(
                self._is_admin(holder.id) for holder in self._repo.get_users_with_role(role_id)
            ):
                raise AccessDeniedError("Admin role required to delete a role held by an administrator")
        return self._repo.delete_role(role_id)
```

`backend/routers/rbac/roles.py::delete_role`

before:
```python
def delete_role(role_id: int, service: RBACService = Depends(_service)) -> None:
    role = service.get_role(role_id)
    ...
    service.delete_role(role_id)
```

after:
```python
def delete_role(
    role_id: int,
    service: RBACService = Depends(_service),
    current_user: User = Depends(get_current_user),
) -> None:
    role = service.get_role(role_id)
    ...
    service.delete_role(role_id, actor_user_id=current_user.id)
```
(`User` and `get_current_user` are already imported in this module.)

### 1.5 T3 — `tv` and `sid_iat` are mandatory

> **Deferred (2026-10-09):** making the claims mandatory broke 393 unit tests (router tests that stub
> `verify_token` with minimal payloads), far above the PD2 threshold of ~40. `core/auth.py` is unchanged;
> do T3 as its own change with the shared `token_payload` helper below.

`backend/core/auth.py::_load_active_user`

before:
```python
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

    # Absolute session lifetime (S5): ...
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
```

after:
```python
    # Revocation (S5): `tv` must be present and equal to the user's current
    # token_version. T3: no tolerance for claim-less tokens any more.
    token_tv = token_payload.get("tv")
    if not isinstance(token_tv, int) or token_tv != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers=AUTHENTICATE_HEADER,
        )

    # Absolute session lifetime (S5): `sid_iat` (original login time) is required.
    sid_iat_raw = token_payload.get("sid_iat")
    if not isinstance(sid_iat_raw, int | float) or (
        datetime.now(UTC) - datetime.fromtimestamp(sid_iat_raw, UTC)
        > timedelta(hours=settings.session_max_age_hours)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers=AUTHENTICATE_HEADER,
        )

    return user
```

Test fixtures: add `tests/unit/helpers/tokens.py`

```python
from __future__ import annotations

import time


def token_payload(user_id: int = 1, *, tv: int = 0, username: str = "tester") -> dict:
    """Minimal valid verify_token payload for tests that stub verify_token."""
    now = int(time.time())
    return {"sub": username, "user_id": user_id, "tv": tv, "sid_iat": now, "iat": now}
```
and make every test double user used with `_load_active_user` carry `token_version=0`.
Run `pytest tests/unit -q --no-cov -x` once after the change, fix the failures with the helper
(PD2: defer T3 if the count is unreasonable).

### 1.6 T4 — refresh window cannot exceed the session cap

`backend/core/config.py`

before:
```python
        self.refresh_token_max_age_hours = self._get_int("REFRESH_TOKEN_MAX_AGE_HOURS", 24)
        self._validate_refresh_token_max_age()
        # Absolute session lifetime ...
        self.session_max_age_hours = self._get_int("SESSION_MAX_AGE_HOURS", 12)
        self._validate_session_max_age()
```

after:
```python
        self.session_max_age_hours = self._get_int("SESSION_MAX_AGE_HOURS", 12)
        self._validate_session_max_age()
        # How stale an expired access token may be when exchanged. Anything above
        # the absolute session cap is unreachable, so it is refused (T4).
        self.refresh_token_max_age_hours = self._get_int(
            "REFRESH_TOKEN_MAX_AGE_HOURS", self.session_max_age_hours
        )
        self._validate_refresh_token_max_age()
```
(Keep the explanatory comment about the absolute lifetime above the session line.)

before:
```python
    def _validate_refresh_token_max_age(self) -> None:
        if self.refresh_token_max_age_hours < 1:
            raise RuntimeError("REFRESH_TOKEN_MAX_AGE_HOURS must be at least 1")
```

after:
```python
    def _validate_refresh_token_max_age(self) -> None:
        if self.refresh_token_max_age_hours < 1:
            raise RuntimeError("REFRESH_TOKEN_MAX_AGE_HOURS must be at least 1")
        if self.refresh_token_max_age_hours > self.session_max_age_hours:
            raise RuntimeError(
                "REFRESH_TOKEN_MAX_AGE_HOURS must not exceed SESSION_MAX_AGE_HOURS"
            )
```

`backend/.env.example` line 7: `REFRESH_TOKEN_MAX_AGE_HOURS=24` → `REFRESH_TOKEN_MAX_AGE_HOURS=12`.
Also fix the docstring in `services/auth/auth_service.py` (~line 83) that describes 24 h as the boundary.

### 1.7 Tests (write first)

| File | Test | Asserts |
|---|---|---|
| `test_users_service.py` (new) / `test_rbac_elevation.py` | `test_user_cannot_change_own_password_via_update_user` | actor == target, password given → `AccessDeniedError` |
| same | `test_admin_cannot_rename_self_via_update_user` | actor admin == target, username given → `AccessDeniedError` |
| same | `test_admin_can_reset_other_users_password` | still allowed |
| same | `test_non_admin_cannot_reactivate_admin` | `set_active(admin_id, True, actor=non_admin)` → `AccessDeniedError` |
| same | `test_non_admin_can_activate_pending_oidc_user` | non-admin target → returns user |
| `test_rbac_service.py` | `test_delete_seeded_permission_conflicts` | `ConflictError`; custom permission deletes fine |
| same | `test_delete_role_held_by_admin_requires_admin` / `..._allowed_for_admin` / `..._actor_none_bypasses` | |
| `test_auth_token_version.py` | `test_request_without_tv_is_rejected`, `test_request_without_sid_iat_is_rejected` | 401 |
| `test_config_*.py` | `test_refresh_window_above_session_cap_is_refused` | `RuntimeError` |

### 1.8 Verification
`ruff check` on touched files; `pytest tests/unit -k "user or rbac or auth or config" --no-cov`;
four guard scripts; full `pytest tests/unit` for the coverage ratchet.

---

## Phase 2 — Webhook and git-lock correctness (W1, W2, W3, W4)

Files: `services/change_requests/webhook_service.py`, `service_factory.py`,
`services/auth/login_rate_limiter.py`, `core/webhook_signatures.py`,
`models/git_repositories.py`, `services/git/repo_lock.py`.
Depends on / conflicts: Phase 6 adds a second limiter factory to `service_factory.py` — trivial merge.

### 2.1 W1 — dedicated webhook limiter

`backend/services/auth/login_rate_limiter.py` (constants block)

before:
```python
LOGIN_USER_RATE_LIMIT_ATTEMPTS = 100
LOGIN_USER_RATE_LIMIT_WINDOW_SECONDS = 15 * 60
```

after:
```python
LOGIN_USER_RATE_LIMIT_ATTEMPTS = 100
LOGIN_USER_RATE_LIMIT_WINDOW_SECONDS = 15 * 60
# Inbound git webhooks: a push burst from CI must not be throttled like a password guess (W1).
WEBHOOK_RATE_LIMIT_ATTEMPTS = 60
WEBHOOK_RATE_LIMIT_WINDOW_SECONDS = 60
```

`backend/service_factory.py` — add next to `_login_user_rate_limiter` (module global
`_webhook_rate_limiter: LoginRateLimiter | None = None`, and extend the existing import from
`services.auth.login_rate_limiter` with the two new constants):

before:
```python
def build_login_user_rate_limiter() -> LoginRateLimiter:
```

after:
```python
def build_webhook_rate_limiter() -> LoginRateLimiter:
    """Per repo+client-IP budget for the inbound git webhook (W1)."""
    global _webhook_rate_limiter
    if _webhook_rate_limiter is None:
        _webhook_rate_limiter = LoginRateLimiter(
            redis_url=settings.redis_url,
            key_prefix="manus-webhook-rl",
            fail_closed=settings.environment != "development",
            attempts=WEBHOOK_RATE_LIMIT_ATTEMPTS,
            window_seconds=WEBHOOK_RATE_LIMIT_WINDOW_SECONDS,
        )
    return _webhook_rate_limiter


def build_login_user_rate_limiter() -> LoginRateLimiter:
```

`backend/services/change_requests/webhook_service.py`

before:
```python
        limiter = service_factory.build_login_rate_limiter()
```
after:
```python
        limiter = service_factory.build_webhook_rate_limiter()
```
Update the module docstring? It already says "per-repo+IP rate limiting" — unchanged. Existing
tests that patch `build_login_rate_limiter` for the webhook (`test_webhook_service.py`) repoint
to `build_webhook_rate_limiter`; `test_service_factory.py` gains a singleton test for it.

### 2.2 W2 — minimum webhook secret length

`backend/models/git_repositories.py` — an empty string must stay valid on **update** (it clears
the secret, see the comment on the update model), so a plain `min_length` is wrong. Add one
shared validator and use it on both request models.

before (create/request model, ~l. 43):
```python
    webhook_secret: str | None = Field(
        None,
        description="Inbound git-webhook secret (GitHub HMAC secret / GitLab token). "
        "Write-only; never returned.",
    )
```
after:
```python
    webhook_secret: str | None = Field(
        None,
        description="Inbound git-webhook secret (GitHub HMAC secret / GitLab token), "
        "at least 16 characters. Write-only; never returned.",
    )

    @field_validator("webhook_secret")
    @classmethod
    def _webhook_secret_min_length(cls, value: str | None) -> str | None:
        return validate_webhook_secret(value)
```
before (update model, ~l. 96): `    webhook_secret: str | None = None` →
after:
```python
    # An empty string clears the stored secret; omitting the field keeps it.
    webhook_secret: str | None = None

    @field_validator("webhook_secret")
    @classmethod
    def _webhook_secret_min_length(cls, value: str | None) -> str | None:
        return validate_webhook_secret(value)
```
and, at module level (add `field_validator` to the pydantic import):
```python
WEBHOOK_SECRET_MIN_LENGTH = 16


def validate_webhook_secret(value: str | None) -> str | None:
    """None keeps, '' clears, anything else must be a real secret (W2)."""
    if value and len(value) < WEBHOOK_SECRET_MIN_LENGTH:
        raise ValueError(
            f"webhook_secret must be at least {WEBHOOK_SECRET_MIN_LENGTH} characters"
        )
    return value
```
Existing rows with a short secret keep working; they are only rejected when re-saved.

### 2.3 W3 — never 500 on a non-ASCII signature header

`backend/core/webhook_signatures.py`

before:
```python
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header_value)
...
    return hmac.compare_digest(secret, header_value)
```
after:
```python
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    # Bytes, not str: compare_digest raises TypeError on non-ASCII str input (W3).
    return hmac.compare_digest(expected.encode("utf-8"), header_value.encode("utf-8"))
...
    return hmac.compare_digest(secret.encode("utf-8"), header_value.encode("utf-8"))
```

### 2.4 W4 — lock timeout fails the step

`backend/services/git/repo_lock.py::acquire_git_repo_lock`

before:
```python
    Returns True when actually acquired -- the caller must then call
    ``release_git_repo_lock`` (typically in a ``finally``) once its git work
    is done. Returns False when Redis was unavailable or acquisition timed
    out (fail-soft: proceed anyway, matching ``git_repo_lock``'s behaviour).
    """
...
    logger.warning(
        "git_repo_lock: timed out waiting for lock, proceeding anyway repo_id=%s",
        git_repository_id,
    )
    return False
```
after:
```python
    Returns True when actually acquired -- the caller must then call
    ``release_git_repo_lock`` (typically in a ``finally``) once its git work
    is done. Returns False only when no cache is configured (fail-soft: the
    deployment has no way to lock). Raises ``RuntimeError`` when the lock is
    held by someone else for longer than ``_ACQUIRE_TIMEOUT_SECONDS`` --
    proceeding would corrupt the shared working tree (W4).
    """
...
    logger.error(
        "git_repo_lock: timed out waiting for lock repo_id=%s", git_repository_id
    )
    raise RuntimeError(
        f"Timed out after {_ACQUIRE_TIMEOUT_SECONDS}s waiting for the lock on git repository "
        f"{git_repository_id}; another run is still using it"
    )
```
Also update the module docstring paragraph "Fail-soft by design: ..." to say the timeout fails
the caller. Callers need no change: `git_repo_lock` and `store_artifact` already release only when
`acquired` is True and the exception propagates through their `finally`/classification
(`RuntimeError` = execution failure per `doc/WORKFLOW-STEPS.md`). Check `store_artifact/executor.py`
~l. 405 still releases correctly when `acquire` raises (the call is before its `try`; confirm
there is nothing to release).

### 2.5 Tests (write first)

| File | Test | Asserts |
|---|---|---|
| `test_webhook_service.py` | `test_webhook_uses_dedicated_limiter` | `build_webhook_rate_limiter` called, login limiter not |
| `test_login_rate_limiter.py` / `test_service_factory.py` | `test_webhook_limiter_budget` | 60/60 s, prefix `manus-webhook-rl`, singleton |
| `test_webhook_signatures.py` | `test_non_ascii_github_signature_is_rejected_not_raised`, `..._gitlab_token...` | returns False |
| `test_git_repositories_models.py` | `test_short_webhook_secret_rejected`, `test_empty_webhook_secret_clears`, `test_none_keeps` | |
| `test_git_repo_lock.py` | `test_acquire_raises_on_timeout` (monkeypatch `_ACQUIRE_TIMEOUT_SECONDS=0`, cache returns False), `test_acquire_without_cache_returns_false` | `RuntimeError` / `False` |

### 2.6 Verification
`pytest tests/unit -k "webhook or repo_lock or git_repositories or rate_limit" --no-cov`; guards; ruff.

---

## Phase 3 — OpenBao hardening (V5–V14, plus SM6 and SM7 which are the same patterns)

Files: `core/vault.py`, `hatchet/worker_services.py`, `services/vault/{auth,config,client,exceptions}.py`,
`services/credentials/credentials_service.py`, `models/credentials.py`, `models/health.py`,
`services/health/ready.py`, `main.py`, `services/secret_manager/{config,infisical_client,openbao_client}.py`,
`doc/VAULT_INTEGRATION.md`.
Depends on / conflicts: Phase 4 (secret-manager steps) builds on `merge_kv` from §3.6 only for the
OpenBao adapter; the two phases do not otherwise overlap.

Phase-local decisions:
- **V12 is informational.** `/health/ready` gains a `vault` check but the overall status/HTTP code
  still depends only on database + Redis. A vault outage degrades vault-backed credentials only;
  taking the whole API out of rotation would be worse. Operators alert on `vault.ok == false`.
- **V5 limits the token, not the env.** Workers stop *logging in* with the management role (no token
  held, no renew loop). `production_guards` is unchanged, so the management role/secret id are
  still required in the shared environment of a production deployment; moving them out of the worker
  environment is a deployment concern (separate env file) noted in `doc/VAULT_INTEGRATION.md`.
- **V9 has no force flag.** If OpenBao is configured (`VAULT_ENABLED=true`) but unreachable, deleting a
  vault credential fails with 503 and is retried later. If vault is not enabled at all (decommissioned),
  the row is removed and a warning logged — there is nothing left to clean.

### 3.1 V5 — management client only where it is used

`backend/core/vault.py`

before:
```python
async def start_vault_services() -> None:
    """Start the runtime + management OpenBao clients and register them as
    ``service_factory`` singletons. No-op unless ``VAULT_ENABLED``.
    ...
    runtime = OpenBaoService(build_vault_config())
    await runtime.startup()
    service_factory.set_vault_service(runtime)

    management = OpenBaoService(build_vault_management_config())
    await management.startup()
    service_factory.set_vault_management_service(management)
```

after:
```python
async def start_vault_services(*, with_management: bool = True) -> None:
    """Start the runtime (and optionally the management) OpenBao client and
    register them as ``service_factory`` singletons. No-op unless ``VAULT_ENABLED``.

    The API process passes ``with_management=True`` (credential writes live in
    ``routers/credentials.py``). Hatchet workers pass ``False``: worker code can
    only read, so holding a write-capable token there is dead weight (V5).
    """
    if not settings.vault_enabled:
        return

    import service_factory
    from services.vault.client import OpenBaoService

    runtime = OpenBaoService(build_vault_config())
    await runtime.startup()
    service_factory.set_vault_service(runtime)

    if with_management:
        management = OpenBaoService(build_vault_management_config())
        await management.startup()
        service_factory.set_vault_management_service(management)
```
`backend/hatchet/worker_services.py`: `await start_vault_services()` → `await start_vault_services(with_management=False)`
and fix the comment above it. `main.py` keeps `await start_vault_services()`.

### 3.2 V6 / SM7 — secrets never appear in `repr()`

`backend/services/vault/auth.py`

before:
```python
from dataclasses import dataclass
...
    client_token: str
```
after:
```python
from dataclasses import dataclass, field
...
    client_token: str = field(repr=False)
```
(`lease_duration`, `renewable`, `period` keep their defaults; `client_token` has no default, so it stays first.)

`backend/services/vault/config.py`

before:
```python
from dataclasses import dataclass
...
    secret_id: str = ""
...
    token: str = ""
...
    client_key: str = ""
```
after:
```python
from dataclasses import dataclass, field
...
    secret_id: str = field(default="", repr=False)
...
    token: str = field(default="", repr=False)
...
    client_key: str = field(default="", repr=False)
```

`backend/services/secret_manager/config.py`: `auth_secret: str` → `auth_secret: str = field(repr=False)`
(import `field`; it is the last field, so no default-ordering problem).
`backend/services/secret_manager/infisical_client.py`: `access_token: str` →
`access_token: str = field(repr=False)` (import `field`).

### 3.3 V7 — tell an expired token from a policy denial

`backend/services/vault/client.py::_request`

before:
```python
        if response.status_code == 403 and authed and _retry_on_403:
            # An expired or revoked token also answers 403. Re-login once and
            # retry transparently so a single expiry never fails a caller (V4).
            self._tokens.invalidate()
            return self._request(method, path, json=json, authed=authed, _retry_on_403=False)
```
after:
```python
        if response.status_code == 403 and authed and _retry_on_403:
            # An expired or revoked token also answers 403, but so does a genuine
            # policy denial. Ask OpenBao whether the token is still good (V7): if it
            # is, this is a denial -- do not burn a login on it.
            if self._token_is_valid(client, headers["X-Vault-Token"]):
                raise VaultPermissionError(
                    f"OpenBao denied {method} {path} (HTTP 403) for {self._cfg.role_label}"
                )
            # Expired/revoked: re-login once and retry transparently (V4).
            self._tokens.invalidate()
            return self._request(method, path, json=json, authed=authed, _retry_on_403=False)
```
Add the helper next to `_request`:
```python
    @staticmethod
    def _token_is_valid(client: httpx.Client, token: str) -> bool:
        try:
            response = client.get(
                "/v1/auth/token/lookup-self", headers={"X-Vault-Token": token}
            )
        except httpx.HTTPError:
            return False
        return response.status_code == 200
```
(`default` policy includes `lookup-self`; add it to the `manus-app`/`manus-manage` HCL in
`doc/VAULT_INTEGRATION.md` only if the runbook policies exclude `default`.) The V4 tests that
simulate expiry with a `MockTransport` must answer `lookup-self` with 403.

### 3.4 V8 — drop the reader's stale cache after a management write/delete

`backend/services/vault/client.py` (next to `delete_kv`):
```python
    def invalidate(self, path: str) -> None:
        """Forget a cached secret (used when another client in this process wrote it, V8)."""
        self._cache.invalidate(path)
```

`backend/services/credentials/credentials_service.py` — two spots, both after the management
call succeeded:

before (`_merge_vault_secret`, after the destroy block): `        return set(merged)`
after:
```python
        reader = self._get_vault_reader()
        if reader is not None:
            reader.invalidate(credential.vault_path)  # V8: the runtime client's 45 s cache
        return set(merged)
```
before (`delete_credential`, after `delete_kv` succeeds — see §3.5 for the full block).

### 3.5 V9 — deleting a vault credential is fail-closed

`backend/services/credentials/credentials_service.py::delete_credential`

before:
```python
        if credential.storage_backend == "vault" and credential.vault_path:
            if self._vault_writer is not None:
                try:
                    self._vault_writer.delete_kv(credential.vault_path)
                except VaultError:
                    logger.warning(
                        "Failed to delete OpenBao secret for credential %s at %s; "
                        "removing the database row anyway",
                        cred_id,
                        credential.vault_path,
                        exc_info=True,
                    )
```
after:
```python
        if credential.storage_backend == "vault" and credential.vault_path:
            if self._vault_writer is None:
                if settings.vault_enabled:
                    raise CredentialVaultNotConfiguredError()
                logger.warning(
                    "Vault is disabled; removing credential %s without deleting %s",
                    cred_id,
                    credential.vault_path,
                )
            else:
                try:
                    self._vault_writer.delete_kv(credential.vault_path)
                except VaultSecretNotFoundError:
                    pass  # already gone: nothing to orphan
                except VaultError as exc:
                    # V9: keep the row, so the operator can retry once OpenBao is back.
                    raise CredentialVaultUnavailableError(str(exc)) from exc
                reader = self._get_vault_reader()
                if reader is not None:
                    reader.invalidate(credential.vault_path)  # V8
```
The router already maps `CredentialVaultUnavailableError` to a sanitised 503
(`routers/credentials.py`), so no router change.

### 3.6 V10 / SM6 — check-and-set merge for KV v2

`backend/services/vault/exceptions.py`:
```python
class VaultConflictError(VaultError):
    """Raised when a KV v2 write loses a check-and-set race (HTTP 400, cas mismatch)."""
```

`backend/services/vault/client.py`

before (`_request`, just before the final `raise VaultError(...)`):
```python
        raise VaultError(f"OpenBao {method} {path} returned HTTP {response.status_code}")
```
after:
```python
        if response.status_code == 400 and "check-and-set" in response.text:
            raise VaultConflictError(f"OpenBao check-and-set conflict at {path}")
        raise VaultError(f"OpenBao {method} {path} returned HTTP {response.status_code}")
```

before (`write_kv`):
```python
    def write_kv(self, path: str, data: dict) -> int | None:
        """Write a new version; return its version number when OpenBao reports it."""
        response = self._request(
            "POST", f"/v1/{self._cfg.mount}/data/{path}", json={"data": data}
        )
        self._cache.set(path, data)
```
after:
```python
    def write_kv(self, path: str, data: dict, *, cas: int | None = None) -> int | None:
        """Write a new version; return its version number when OpenBao reports it.

        ``cas`` makes the write conditional on the current version (0 = create only if
        absent); a mismatch raises ``VaultConflictError`` (V10).
        """
        body: dict = {"data": data}
        if cas is not None:
            body["options"] = {"cas": cas}
        response = self._request("POST", f"/v1/{self._cfg.mount}/data/{path}", json=body)
        self._cache.set(path, data)
```
and add after `write_kv`:
```python
    def read_kv_with_version(self, path: str) -> tuple[dict, int | None]:
        """Uncached read returning ``(data, version)`` for read-modify-write (V10)."""
        body = self._request("GET", f"/v1/{self._cfg.mount}/data/{path}").json() or {}
        envelope = body.get("data") or {}
        data = envelope.get("data")
        if data is None:
            raise VaultSecretNotFoundError(f"OpenBao path holds no secret data: {path}")
        version = (envelope.get("metadata") or {}).get("version")
        return dict(data), version if isinstance(version, int) else None

    def merge_kv(
        self, path: str, new_fields: dict, *, attempts: int = 2
    ) -> tuple[dict, int | None]:
        """Read-merge-write ``new_fields`` into the secret at *path* with check-and-set.

        Returns ``(merged, new_version)``. A lost race is re-read and retried once;
        a second loss raises ``VaultConflictError``. Never served from the TTL cache,
        so concurrent writers in other processes cannot be overwritten (V10 / SM6).
        """
        for attempt in range(attempts):
            try:
                current, version = self.read_kv_with_version(path)
            except VaultSecretNotFoundError:
                current, version = {}, 0  # cas=0: create only if it still does not exist
            merged = {**current, **new_fields}
            try:
                return merged, self.write_kv(path, merged, cas=version)
            except VaultConflictError:
                if attempt == attempts - 1:
                    raise
        raise VaultConflictError(path)  # unreachable; keeps the type checker honest
```
Import `VaultConflictError` in the existing exceptions import block.

`backend/services/credentials/credentials_service.py::_merge_vault_secret`

before:
```python
        try:
            existing = self._vault_writer.read_kv(credential.vault_path)
        except VaultSecretNotFoundError:
            existing = {}
        except VaultError as exc:
            raise CredentialVaultUnavailableError(str(exc)) from exc
        merged = {**existing, **new_fields}
        try:
            new_version = self._vault_writer.write_kv(credential.vault_path, merged)
        except VaultError as exc:
            raise CredentialVaultUnavailableError(str(exc)) from exc
```
after:
```python
        try:
            merged, new_version = self._vault_writer.merge_kv(credential.vault_path, new_fields)
        except VaultError as exc:
            raise CredentialVaultUnavailableError(str(exc)) from exc
```

`backend/services/secret_manager/openbao_client.py::set_field`

before:
```python
        try:
            current = self._service.read_kv(path)
        except VaultSecretNotFoundError:
            current = {}
        except VaultError as exc:
            raise SecretManagerUnavailableError(str(exc)) from exc
        merged = {**current, field: value}
        try:
            return self._service.write_kv(path, merged)
        except VaultError as exc:
            raise SecretManagerUnavailableError(str(exc)) from exc
```
after:
```python
        try:
            _merged, version = self._service.merge_kv(path, {field: value})
        except VaultError as exc:
            raise SecretManagerUnavailableError(str(exc)) from exc
        return version
```
(Mock-based tests in `test_credentials_service_vault.py` and `test_secret_manager_openbao_client.py`
that stub `read_kv`/`write_kv` on the writer are rewritten to stub `merge_kv`; add real-transport
tests in `test_vault_client.py`.)

### 3.7 V11 — bounds on secret material

`backend/models/credentials.py` (both `CredentialCreate` and `CredentialUpdate`)

before:
```python
    password: str | None = None
    ssh_private_key: str | None = None
    ssh_passphrase: str | None = None
```
after:
```python
    password: str | None = Field(default=None, max_length=MAX_PASSWORD_LENGTH)
    ssh_private_key: str | None = Field(default=None, max_length=MAX_SSH_KEY_LENGTH)
    ssh_passphrase: str | None = Field(default=None, max_length=MAX_PASSWORD_LENGTH)
```
with, at module level:
```python
MAX_PASSWORD_LENGTH = 1024        # passwords, tokens, passphrases, shared-secret passphrases
MAX_SSH_KEY_LENGTH = 64 * 1024    # PEM private keys
```

### 3.8 V12 — vault status in `/health/ready`

`backend/models/health.py`

before:
```python
class ReadyResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    database: ReadyCheck
    redis: ReadyCheck
```
after:
```python
class ReadyResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    database: ReadyCheck
    redis: ReadyCheck
    # Present only when VAULT_ENABLED. Informational: a vault outage degrades
    # vault-backed credentials, it does not make the API unready (V12).
    vault: ReadyCheck | None = None
```

`backend/services/health/ready.py`

before:
```python
    redis_ok: bool,
    redis_error: str | None,
) -> tuple[int, ReadyResponse]:
...
            redis=ReadyCheck(ok=redis_ok, error=redis_error),
        ),
```
after:
```python
    redis_ok: bool,
    redis_error: str | None,
    vault_ok: bool | None = None,
    vault_error: str | None = None,
) -> tuple[int, ReadyResponse]:
...
            redis=ReadyCheck(ok=redis_ok, error=redis_error),
            vault=None if vault_ok is None else ReadyCheck(ok=vault_ok, error=vault_error),
        ),
```
(`all_ok` stays `database_ok and redis_ok`.)

`backend/main.py::health_ready` — before the `build_ready_response(` call:
```python
    vault_ok: bool | None = None
    vault_error: str | None = None
    if settings.vault_enabled:
        runtime = service_factory.get_vault_service()
        vault_ok = bool(runtime is not None and runtime.healthy)
        vault_error = None if vault_ok else "unavailable"
```
and pass `vault_ok=vault_ok, vault_error=vault_error` to `build_ready_response`.

### 3.9 V13 — warn about a readable SecretID file

`backend/services/vault/config.py::resolved_secret_id`

before:
```python
        if self.secret_id_file:
            with open(self.secret_id_file, encoding="utf-8") as handle:
                return handle.read().strip()
```
after:
```python
        if self.secret_id_file:
            mode = os.stat(self.secret_id_file).st_mode
            if mode & 0o077:
                logger.warning(
                    "VAULT secret_id_file %s is readable by group/others (mode %o); "
                    "restrict it to 0400/0600",
                    self.secret_id_file,
                    mode & 0o777,
                )
            with open(self.secret_id_file, encoding="utf-8") as handle:
                return handle.read().strip()
```
(add `import logging`, `import os`, `logger = logging.getLogger(__name__)`).

### 3.10 V14 — bounded SecretID TTL in the runbook

`doc/VAULT_INTEGRATION.md` (step 3, both `bao write auth/approle/role/...` blocks and the sentence
above them)

before: `secret_id_num_uses=0 secret_id_ttl=0 \`
after: `secret_id_num_uses=0 secret_id_ttl=2160h \`
and add one sentence: "`secret_id_ttl=2160h` (90 days) makes an un-rotated SecretID expire on its
own; rotate it as described under *SecretID rotation* before then. `secret_id_num_uses=0` stays so
redeploys do not exhaust it."

### 3.11 Tests (write first)

| File | Test | Asserts |
|---|---|---|
| `test_vault_client.py` | `test_write_kv_sends_cas`, `test_merge_kv_retries_once_on_cas_conflict`, `test_merge_kv_second_conflict_raises`, `test_merge_kv_creates_with_cas_zero`, `test_403_with_valid_token_does_not_relogin`, `test_403_with_invalid_token_relogs_in_once`, `test_invalidate_drops_cache` | |
| `test_credentials_service_vault.py` | `test_delete_vault_failure_keeps_row`, `test_delete_not_found_in_vault_still_deletes`, `test_delete_vault_disabled_deletes_with_warning`, `test_delete_vault_enabled_without_writer_raises`, `test_update_invalidates_reader_cache` | |
| `test_vault_*` / `test_secret_manager_*` | `test_secret_not_in_repr` (VaultToken, VaultConfig, SecretManagerConnectionConfig, `_InfisicalToken`) | `"s3cret" not in repr(obj)` |
| `test_vault_start_services.py` (new) | `test_workers_skip_management_client` | `with_management=False` → management singleton stays `None` |
| `test_credentials_models.py` | `test_secret_length_bounds` | 1025-char password and 65537-char key → `ValidationError` |
| `test_health_ready.py` | `test_vault_check_reported_but_not_blocking` | vault down + db/redis ok → 200, `vault.ok == false` |
| `test_vault_config.py` | `test_group_readable_secret_id_file_warns` (`caplog`) | WARNING logged |
| `test_secret_manager_openbao_client.py` | `test_set_field_uses_merge_kv` | |

### 3.12 Verification
`pytest tests/unit -k "vault or credentials or health or secret_manager" --no-cov`; guards; ruff.
Opt-in live check (not CI): `tests/integration/test_vault_integration.py` still passes against the
docker dev OpenBao, including a two-writer CAS case.

---

## Phase 4 — Secret Manager steps (SM5, SM8, SM9, SM11, Infisical verification)

Files: new `services/secret_manager/validation.py`, `services/secret_manager/{service,registry,connection_service}.py`,
`models/secret_manager.py`, `workflow_steps/secret_{get,set,generate}/executor.py`,
`tests/unit/test_secret_manager_config.py` (new).
Depends on / conflicts: none (SM6/SM7 are in Phase 3). The shared `_INVALID_SEGMENT_CHARS` in
`device_template.py` is **not** changed (it also sanitises local filenames for `store-artifact`);
the stricter rule lives in the new validator instead.

### 4.1 SM5 — one validator for fields and rendered paths

new — `backend/services/secret_manager/validation.py`
```python
"""Input rules for the pieces of a Secret Manager request that end up in a URL path."""

from __future__ import annotations

import re

# Starts alphanumeric/underscore, so "." and ".." can never match.
_FIELD_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,254}$")
_PATH_CHARS_RE = re.compile(r"^[A-Za-z0-9 _.@=+/-]+$")


def validate_field(field: str) -> str:
    """A secret key/field name (Infisical puts it in the URL path)."""
    if not _FIELD_RE.fullmatch(field):
        raise ValueError(
            "field must be 1-255 characters of letters, digits, '_', '.', '-' "
            "and must not start with '.' or '-'"
        )
    return field


def validate_kv_path(path: str) -> str:
    """A *rendered* secret path (after device-template substitution)."""
    segments = path.split("/")
    if (
        not path
        or path.startswith("/")
        or not _PATH_CHARS_RE.fullmatch(path)
        or any(segment in ("", ".", "..") for segment in segments)
    ):
        raise ValueError(
            f"invalid secret path {path!r}: use letters, digits, space and _ . @ = + - "
            "with '/' separators, no empty, '.' or '..' segments"
        )
    return path
```

`backend/workflow_steps/secret_{get,set,generate}/executor.py::_parse_config` (same edit in all three)

before:
```python
    field = str(config.get("field") or "key").strip()
    if not field:
        raise ValueError(f"{_STEP_ID}: field is required")
```
after:
```python
    field = str(config.get("field") or "key").strip()
    if not field:
        raise ValueError(f"{_STEP_ID}: field is required")
    try:
        field = validate_field(field)
    except ValueError as exc:
        raise ValueError(f"{_STEP_ID}: {exc}") from exc
```
(import `from services.secret_manager.validation import validate_field`).

`backend/services/secret_manager/service.py` — validate the rendered path once, for both backends
(combined with SM8 below, shown in §4.2).

### 4.2 SM8 — no blocking HTTP on the event loop

`backend/services/secret_manager/service.py`

before:
```python
from sqlalchemy.orm import Session

import service_factory
from services.secret_manager.client import SecretVersionInfo
from services.secret_manager.policy import SecretGenerationPolicy, generate_secret


class SecretManagerService:
    ...
    async def get_field(
        self, connection_id: int, path: str, field: str, *, version: int | None = None
    ) -> str | None:
        client = await service_factory.get_secret_manager_registry().get_or_create(
            connection_id, self._db
        )
        return client.get_field(path, field, version=version)

    async def set_field(
        self, connection_id: int, path: str, field: str, value: str
    ) -> int | None:
        client = await service_factory.get_secret_manager_registry().get_or_create(
            connection_id, self._db
        )
        return client.set_field(path, field, value)
    ...
        client = await service_factory.get_secret_manager_registry().get_or_create(
            connection_id, self._db
        )
        return client.get_field_history(path, field)
```

after:
```python
import asyncio

from sqlalchemy.orm import Session

import service_factory
from services.secret_manager.client import SecretVersionInfo
from services.secret_manager.policy import SecretGenerationPolicy, generate_secret
from services.secret_manager.validation import validate_field, validate_kv_path


class SecretManagerService:
    ...
    async def get_field(
        self, connection_id: int, path: str, field: str, *, version: int | None = None
    ) -> str | None:
        validate_kv_path(path)
        validate_field(field)
        client = await service_factory.get_secret_manager_registry().get_or_create(
            connection_id, self._db
        )
        # The adapters use synchronous httpx; keep the worker's event loop free (SM8).
        return await asyncio.to_thread(client.get_field, path, field, version=version)

    async def set_field(
        self, connection_id: int, path: str, field: str, value: str
    ) -> int | None:
        validate_kv_path(path)
        validate_field(field)
        client = await service_factory.get_secret_manager_registry().get_or_create(
            connection_id, self._db
        )
        return await asyncio.to_thread(client.set_field, path, field, value)
    ...
        validate_kv_path(path)
        validate_field(field)
        client = await service_factory.get_secret_manager_registry().get_or_create(
            connection_id, self._db
        )
        return await asyncio.to_thread(client.get_field_history, path, field)
```
Also fix the module docstring paragraph that says the calls are "deliberately synchronous".
A `ValueError` raised here for a bad rendered path propagates as a configuration error
(`ValueError` = config per `doc/WORKFLOW-STEPS.md`), same as a bad template.

`backend/services/secret_manager/registry.py` — per-connection locks, so one connection's DB
read + decrypt + login no longer blocks every other connection.

before:
```python
    def __init__(self) -> None:
        self._clients: dict[int, _CachedClient] = {}
        self._lock = asyncio.Lock()
```
after:
```python
    def __init__(self) -> None:
        self._clients: dict[int, _CachedClient] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock_for(self, connection_id: int) -> asyncio.Lock:
        # Created synchronously (no await), so two coroutines cannot race on it.
        lock = self._locks.get(connection_id)
        if lock is None:
            lock = self._locks[connection_id] = asyncio.Lock()
        return lock
```
In `get_or_create` replace the three `async with self._lock:` with
`lock = self._lock_for(connection_id)` (once, before the `while True`) and `async with lock:`.
`invalidate`: `async with self._lock:` → `async with self._lock_for(connection_id):`.
`shutdown_all`:

before:
```python
        async with self._lock:
            cached_clients = list(self._clients.values())
            self._clients.clear()
```
after:
```python
        # No await between the copy and the clear, so this is atomic on the event loop.
        cached_clients = list(self._clients.values())
        self._clients.clear()
        self._locks.clear()
```

### 4.3 SM9 — strict connection config, bounded names, correct `version`

`backend/services/secret_manager/connection_service.py`

before:
```python
def _validate_backend_config(backend: str, backend_config: dict[str, Any]) -> None:
    if backend not in _VALID_BACKENDS:
        raise ValueError(f"Unknown secret manager backend: {backend!r}")
    required = _REQUIRED_BACKEND_CONFIG_KEYS[backend]
    missing = [key for key in required if not str(backend_config.get(key) or "").strip()]
    if missing:
        raise ValueError(
            f"backend_config for '{backend}' is missing required field(s): {', '.join(missing)}"
        )
```
after:
```python
_OPTIONAL_BACKEND_CONFIG_KEYS: dict[str, tuple[str, ...]] = {
    "openbao": ("namespace",),
    "infisical": (),
}
_MAX_BACKEND_CONFIG_VALUE_LENGTH = 255


def _validate_backend_config(backend: str, backend_config: dict[str, Any]) -> None:
    if backend not in _VALID_BACKENDS:
        raise ValueError(f"Unknown secret manager backend: {backend!r}")
    required = _REQUIRED_BACKEND_CONFIG_KEYS[backend]
    missing = [key for key in required if not str(backend_config.get(key) or "").strip()]
    if missing:
        raise ValueError(
            f"backend_config for '{backend}' is missing required field(s): {', '.join(missing)}"
        )
    allowed = set(required) | set(_OPTIONAL_BACKEND_CONFIG_KEYS[backend])
    unknown = sorted(set(backend_config) - allowed)
    if unknown:
        raise ValueError(
            f"backend_config for '{backend}' has unknown field(s): {', '.join(unknown)}"
        )
    for key, value in backend_config.items():
        if not isinstance(value, str) or len(value) > _MAX_BACKEND_CONFIG_VALUE_LENGTH:
            raise ValueError(
                f"backend_config.{key} must be a string of at most "
                f"{_MAX_BACKEND_CONFIG_VALUE_LENGTH} characters"
            )
```
(`namespace` may be sent as `""`/`null`; treat `None` as absent: pass
`{k: v for k, v in backend_config.items() if v is not None}` into this function from
`_validate_connection`.)

`backend/models/secret_manager.py`

before:
```python
class SecretManagerConnectionRequest(BaseModel):
    name: str = Field(..., description="Unique connection name")
...
class SecretManagerConnectionUpdateRequest(BaseModel):
    name: str | None = None
    backend: SecretManagerBackend | None = None
    credential_name: str | None = None
```
after:
```python
class SecretManagerConnectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255, description="Unique connection name")
...
class SecretManagerConnectionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    backend: SecretManagerBackend | None = None
    credential_name: str | None = Field(default=None, max_length=255)
```
(import `ConfigDict`; update the module docstring — `backend_config` stays a free dict at the request
layer on purpose, validated per backend in the service.)

`backend/workflow_steps/secret_get/executor.py::_parse_config`

before:
```python
    raw_version = config.get("version")
    version = int(raw_version) if isinstance(raw_version, int) else None
```
after:
```python
    raw_version = config.get("version")
    version: int | None = None
    if raw_version is not None and raw_version != "":
        try:
            version = int(raw_version)
        except (TypeError, ValueError):
            raise ValueError(f"{_STEP_ID}: version must be an integer, got {raw_version!r}") from None
        if version < 1:
            raise ValueError(f"{_STEP_ID}: version must be 1 or greater")
```
(`bool` is an `int` subclass: reject it explicitly with `isinstance(raw_version, bool)` → `ValueError`.)

### 4.4 SM11 — test the config loader

new — `backend/tests/unit/test_secret_manager_config.py`: `load_connection_config` for (a) missing
connection → `ValueError("… not found")`, (b) inactive → `"… is not active"`, (c) no `credential_name`
→ empty `auth_id`/`auth_secret`, (d) SSH credential rejected (`secret_manager_auth` raises) with the
connection name in the message, (e) happy path returns the resolved username/password.
Patch `SecretManagerConnectionService.get_connection` and `CredentialManager.secret_manager_auth`.

### 4.5 Infisical verification (procedure, no code until it is run)

The `PATCH`/`DELETE` shapes and version-pinned reads in `infisical_client.py` are documented as
unverified (`doc/SECRET_MANAGER_INTEGRATION.md` l. 329–347). Run once, then correct the code and the doc:

1. `cd docker/infisical && cp .env.example .env` (fill the secrets), `docker compose up -d`.
2. In the UI create a project, an environment, and a Universal Auth machine identity with read/write on
   `/network`; store its client id/secret as a **global `generic` credential**.
3. Create a Secret Manager connection (`backend=infisical`, `verify_ssl=false` is allowed only with
   `ENV=development`), press *Test* — expect success (SM1).
4. Run a throwaway workflow: `secret-set` (create) → `secret-set` (update, exercises `PATCH`) →
   `secret-get` → `secret-get` with `version=1` (exercises the `version` query param).
5. Record in `doc/SECRET_MANAGER_INTEGRATION.md`: confirmed verbs/status codes, whether `version`
   is honoured, and whether `get_field_history` can be implemented (replace the warning stub if so).
6. Fix whatever differs in `infisical_client.py` and add the observed bodies as `MockTransport` fixtures
   in `test_secret_manager_infisical_client.py`.

### 4.6 Tests (write first)

| File | Test | Asserts |
|---|---|---|
| `test_secret_manager_validation.py` (new) | `test_field_rejects_dotdot_slash_query`, `test_field_accepts_normal_names`, `test_path_rejects_hash_percent_dotdot_empty_segment`, `test_path_accepts_device_paths` | |
| `test_secret_manager_service.py` (new) | `test_get_field_runs_in_thread`, `test_bad_path_raises_before_client_lookup` | `asyncio.to_thread` used; registry not called |
| `test_secret_manager_registry.py` | `test_slow_connection_does_not_block_another`, `test_invalidate_one_connection_keeps_others` | two connections with an artificially slow `ensure_started` |
| `test_secret_manager_connection_service.py` | `test_unknown_backend_config_key_rejected`, `test_non_string_or_oversize_value_rejected`, `test_namespace_null_is_allowed` | |
| `test_secret_manager_router.py` | `test_name_too_long_is_422`, `test_extra_field_is_422` | |
| `test_secret_get_step.py` | `test_version_string_is_coerced`, `test_version_garbage_raises`, `test_version_zero_raises` | |

### 4.7 Verification
`pytest tests/unit -k "secret" --no-cov`; guards; ruff.

---

## Phase 5 — Batfish robustness (B3 row cap, B4, B5, B6, B7, B8)

Files: `services/batfish/client.py`, `services/batfish/query_helpers.py`, `models/batfish.py`,
`workflow_steps/batfish_init_snapshot/executor.py`, `workflow_steps/batfish_validate_facts/executor.py`.
Depends on / conflicts: the rate-limit half of B3 is Phase 6. Independent of Phases 1–4.

Phase-local decision (B5): the plan does **not** rename custom networks (a `manus-named-` prefix would
break every query step, the discovery picker and existing shared networks such as the nightly
production refresh). Instead `batfish-init-snapshot` refuses to write into *another workflow's
default network* (`manus-workflow-<other id>`). Custom shared networks stay shared by design.

### 5.1 B4 — per-key session creation, bounded cache, cheap list-only sessions

`backend/services/batfish/client.py`

before:
```python
import asyncio
import json
import logging
from typing import Any, cast
...
class BatfishService:
    def __init__(self) -> None:
        self._sessions: dict[tuple[str, int, str], Session] = {}
        self._lock = asyncio.Lock()
...
    async def shutdown(self) -> None:
        self._sessions.clear()
        logger.info("BatfishService shut down")
```
after:
```python
import asyncio
import json
import logging
from collections import OrderedDict
from typing import Any, cast

# One Session (with its loaded question catalogue) per (host, port, network). Networks are
# created per workflow, so cap the cache and drop the least-recently-used entry (B4).
MAX_CACHED_SESSIONS = 64
...
class BatfishService:
    def __init__(self) -> None:
        self._sessions: OrderedDict[tuple[str, int, str], Session] = OrderedDict()
        self._session_locks: dict[tuple[str, int, str], asyncio.Lock] = {}

    ...
    async def shutdown(self) -> None:
        self._sessions.clear()
        self._session_locks.clear()
        logger.info("BatfishService shut down")
```

before (`list_networks._list` and `check_health._check`, identical line):
```python
            session = Session(host=connection.host, port=connection.port)
            return session.list_networks()
```
after (both):
```python
            # list_networks() needs no question templates: skip the extra HTTP round trip (B4).
            session = Session(host=connection.host, port=connection.port, load_questions=False)
            return session.list_networks()
```

before (`_get_session`):
```python
    async def _get_session(self, connection: BatfishConnection, network: str) -> Session:
        key = (connection.host, connection.port, network)
        async with self._lock:
            session = self._sessions.get(key)
            if session is None:
                session = await asyncio.to_thread(
                    Session, host=connection.host, port=connection.port
                )
                await asyncio.to_thread(session.set_network, network)
                self._sessions[key] = session
            return session
```
after:
```python
    async def _get_session(self, connection: BatfishConnection, network: str) -> Session:
        key = (connection.host, connection.port, network)
        session = self._sessions.get(key)
        if session is not None:
            self._sessions.move_to_end(key)
            return session

        # A lock per key: a slow coordinator for one network no longer serialises every
        # other Batfish call in the process (B4). Created synchronously, so it cannot race.
        lock = self._session_locks.setdefault(key, asyncio.Lock())
        async with lock:
            session = self._sessions.get(key)
            if session is None:
                session = await asyncio.to_thread(
                    Session, host=connection.host, port=connection.port
                )
                await asyncio.to_thread(session.set_network, network)
                self._sessions[key] = session
                while len(self._sessions) > MAX_CACHED_SESSIONS:
                    evicted, _ = self._sessions.popitem(last=False)
                    self._session_locks.pop(evicted, None)
            else:
                self._sessions.move_to_end(key)
            return session
```
(`self._lock` has no other users in this module — grep `self._lock` before deleting; the old
`asyncio.Lock()` in `__init__` is removed above.)

### 5.2 B3 — cap what an ad-hoc query returns

`backend/models/batfish.py` (add `model_validator` to the pydantic import)

before:
```python
    facts_by_node: dict[str, Any] | None = None
```
(last field of `BatfishQueryResponse`)

after:
```python
    facts_by_node: dict[str, Any] | None = None
    # True when rows / facts_by_node were cut to MAX_PREVIEW_ROWS (B3).
    truncated: bool = False

    @model_validator(mode="after")
    def _cap_size(self) -> "BatfishQueryResponse":
        """One central cap so every ad-hoc query path (routes, facts, generic) is bounded
        without touching each call site: a full-fleet RIB must not be serialised to the editor."""
        if len(self.rows) > MAX_PREVIEW_ROWS:
            self.rows = self.rows[:MAX_PREVIEW_ROWS]
            self.truncated = True
        if self.facts_by_node is not None and len(self.facts_by_node) > MAX_PREVIEW_NODES:
            self.facts_by_node = dict(list(self.facts_by_node.items())[:MAX_PREVIEW_NODES])
            self.truncated = True
        return self
```
with, near the top of the module:
```python
MAX_PREVIEW_ROWS = 5000
MAX_PREVIEW_NODES = 1000
```
Frontend: show a "Result truncated to 5 000 rows" notice when `truncated` is true in the Template
Editor's Batfish Options modal (`frontend/src/components/features/templates/**`; find with
`grep -rn "BatfishQueryResponse" frontend/src`) and add `truncated?: boolean` to its TypeScript type.

### 5.3 B5 — do not write into another workflow's default network

`backend/workflow_steps/batfish_init_snapshot/executor.py`

before:
```python
    network = str(merged_config.get("network_name") or "").strip() or (
        f"manus-workflow-{context.workflow_id}"
    )
    snapshot_name = f"run-{run.id}"
```
after:
```python
    network = str(merged_config.get("network_name") or "").strip() or (
        f"manus-workflow-{context.workflow_id}"
    )
    # B5: a custom network_name may be a deliberately shared network, but it must not
    # collide with *another workflow's* default network (overwrite=True + retention
    # sweep would destroy that workflow's snapshots).
    other = _DEFAULT_NETWORK_RE.fullmatch(network)
    if other is not None and int(other.group(1)) != context.workflow_id:
        raise ValueError(
            f"{_STEP_ID}: network_name {network!r} is the default network of workflow "
            f"{other.group(1)}; choose a different name"
        )
    snapshot_name = f"run-{run.id}"
```
and at module level (`import re`):
```python
_DEFAULT_NETWORK_RE = re.compile(r"manus-workflow-(\d+)")
```

### 5.4 B6 — sanitise the device id used as a filename

`backend/workflow_steps/batfish_init_snapshot/executor.py::_write_device_configs`

before:
```python
        (configs_dir / f"{device_id}.cfg").write_text(text, encoding="utf-8")
```
after:
```python
        (configs_dir / f"{sanitize_path_segment(device_id)}.cfg").write_text(text, encoding="utf-8")
```
(import `from services.workflow_context.device_template import sanitize_path_segment`; it raises
`ValueError` for an id that sanitises to nothing — that surfaces as a configuration error.)

### 5.5 B7 — YAML parsing off the event loop

`backend/workflow_steps/batfish_validate_facts/executor.py` — two call sites.

before (rendered path, ~l. 127):
```python
    text = await artifact_service.resolve(items[0].artifact_ref)
    nodes, error = _parse_nodes_yaml(text)
```
after:
```python
    text = await artifact_service.resolve(items[0].artifact_ref)
    nodes, error = await asyncio.to_thread(_parse_nodes_yaml, text)
```
before (git corpus, ~l. 165):
```python
        text = await asyncio.to_thread(path.read_text, "utf-8")
        nodes, error = _parse_nodes_yaml(text)
```
after:
```python
        text = await asyncio.to_thread(path.read_text, "utf-8")
        nodes, error = await asyncio.to_thread(_parse_nodes_yaml, text)
```

### 5.6 B8 — reject pybatfish meta-parameters on the generic endpoint

`backend/services/batfish/query_helpers.py::query_generic`

before:
```python
    clean_params = {k: _or_none(v) for k, v in (params or {}).items()}
    clean_params = {k: v for k, v in clean_params.items() if v is not None}
```
after:
```python
    reserved = _RESERVED_GENERIC_PARAMS & set(params or {})
    if reserved:
        raise ValueError(
            f"parameter(s) {', '.join(sorted(reserved))} are reserved and cannot be set "
            "through the ad-hoc endpoint"
        )
    clean_params = {k: _or_none(v) for k, v in (params or {}).items()}
    clean_params = {k: v for k, v in clean_params.items() if v is not None}
```
with, next to `GENERIC_QUESTION_ALLOWLIST`:
```python
# pybatfish accepts these on every question (rename the instance / change exclusions);
# the ad-hoc endpoint does not mean to expose them (B8).
_RESERVED_GENERIC_PARAMS = frozenset({"question_name", "exclusions"})
```
`ValueError` is already mapped to HTTP 400 by the router.

### 5.7 Tests (write first)

| File | Test | Asserts |
|---|---|---|
| `test_batfish_client.py` | `test_slow_session_for_one_network_does_not_block_another` | two keys, one `Session` ctor sleeps; the other returns immediately |
| same | `test_session_cache_evicts_lru` | `MAX_CACHED_SESSIONS + 1` networks → oldest dropped, lock entry removed |
| same | `test_list_networks_uses_load_questions_false` | ctor called with `load_questions=False` |
| `test_batfish_models.py` | `test_response_rows_capped_and_flagged`, `test_response_under_cap_not_flagged`, `test_facts_by_node_capped` | |
| `test_batfish_init_snapshot.py` | `test_refuses_other_workflows_default_network`, `test_allows_own_default_network_name`, `test_allows_custom_shared_network`, `test_device_id_with_slash_is_sanitised` | |
| `test_batfish_validate_facts.py` | `test_yaml_parsed_in_thread` (patch `asyncio.to_thread`, assert called with `_parse_nodes_yaml`) | |
| `test_batfish_query_helpers.py` | `test_generic_rejects_question_name_and_exclusions` | `ValueError` |

### 5.8 Verification
`pytest tests/unit -k batfish --no-cov`; guards; ruff; frontend `npx tsc --noEmit` for the `truncated` type.

---

## Phase 6 — Generic per-user rate limiting (S9, SM10, B3 limit)

Files: new `core/rate_limit.py`, `service_factory.py`, and one added dependency each in
`routers/netmiko.py`, `routers/git/operations.py`, `routers/templates.py`,
`routers/sources/ise/ops.py`, `routers/sources/nautobot/ops.py`, `routers/secret_manager.py`,
`routers/sources/batfish/query.py`.
Depends on / conflicts: `service_factory.py` also gains a factory in Phase 2 (trivial merge).

Phase-local decision: unlike login, these limiters **fall back to an in-process window when Redis is
down** (`fail_closed=False`). Throttling is a protection against runaway use, not an
authentication control; a Redis outage must not stop operators running workflows.
(Supersedes the fail-closed wording of PD7.)

### 6.1 The dependency

new — `backend/core/rate_limit.py`
```python
"""Per-user rate limiting for expensive endpoints (S9).

    @router.post("/sync", dependencies=[Depends(rate_limited("git-sync", attempts=10, window_seconds=60))])

Keyed on the authenticated user id, so one user cannot starve the others and a shared
NAT'd office is not throttled as one client. Every call counts (success or failure).
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, status

import service_factory
from core.auth import get_current_user
from core.models.users import User
from services.auth.login_rate_limiter import RateLimitExceededError


def rate_limited(bucket: str, *, attempts: int, window_seconds: int) -> Callable[..., None]:
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

    return dependency
```
(`get_current_user` is already resolved once per request by FastAPI's dependency cache, so this adds
no second user lookup.)

`backend/service_factory.py` — next to the other limiter factories, plus a module global
`_user_rate_limiters: dict[str, LoginRateLimiter] = {}`:

before:
```python
def build_login_user_rate_limiter() -> LoginRateLimiter:
```
after:
```python
def build_user_rate_limiter(bucket: str, attempts: int, window_seconds: int) -> LoginRateLimiter:
    """One sliding-window limiter per named bucket (S9). Falls back to an in-process
    window when Redis is down rather than blocking the endpoint."""
    limiter = _user_rate_limiters.get(bucket)
    if limiter is None:
        limiter = _user_rate_limiters[bucket] = LoginRateLimiter(
            redis_url=settings.redis_url,
            key_prefix=f"manus-rl:{bucket}",
            fail_closed=False,
            attempts=attempts,
            window_seconds=window_seconds,
        )
    return limiter


def build_login_user_rate_limiter() -> LoginRateLimiter:
```

### 6.2 Where it is applied

| Endpoint(s) | Bucket | Budget | Why |
|---|---|---|---|
| `POST /netmiko/run-commands` (router-level on `routers/netmiko.py`) | `netmiko` | 10 / 60 s | opens SSH sessions to devices |
| `POST /git/{repo_id}/sync`, `/remove-and-sync` | `git-sync` | 10 / 60 s | clone/pull |
| `POST /templates/render` | `template-render` | 60 / 60 s | CPU |
| every route of `routers/sources/ise/ops.py` (router-level) | `ise-ops` | 120 / 60 s | external ISE API |
| `GET /sources/nautobot/{id}/analyze` | `nautobot-analyze` | 20 / 60 s | full inventory query |
| `POST /secret-manager/connections/{id}/test` (SM10) | `secret-manager-test` | 10 / 60 s | live login to an external system |
| every route of `routers/sources/batfish/query.py` (router-level, B3) | `batfish-query` | 30 / 60 s | up to 5 000 rows each |

Examples (before → after):

`backend/routers/netmiko.py`
```python
# before
router = APIRouter(
    prefix="/netmiko",
    tags=["netmiko"],
    dependencies=[
        Depends(get_current_user),
        Depends(require_permission("netmiko", "execute")),
    ],
)
# after
router = APIRouter(
    prefix="/netmiko",
    tags=["netmiko"],
    dependencies=[
        Depends(get_current_user),
        Depends(require_permission("netmiko", "execute")),
        Depends(rate_limited("netmiko", attempts=10, window_seconds=60)),
    ],
)
```
`backend/routers/git/operations.py`
```python
# before
@router.post("/sync", dependencies=[Depends(require_permission("git.operations", "execute"))])
# after
@router.post(
    "/sync",
    dependencies=[
        Depends(require_permission("git.operations", "execute")),
        Depends(rate_limited("git-sync", attempts=10, window_seconds=60)),
    ],
)
```
(and the same added line in the `remove-and-sync` decorator's `dependencies=[...]`).

`backend/routers/secret_manager.py`
```python
# before
@router.post(
    "/{connection_id}/test",
    response_model=SecretManagerConnectionTestResponse,
    dependencies=[Depends(require_permission("secret_manager.connections", "write"))],
)
# after
@router.post(
    "/{connection_id}/test",
    response_model=SecretManagerConnectionTestResponse,
    dependencies=[
        Depends(require_permission("secret_manager.connections", "write")),
        Depends(rate_limited("secret-manager-test", attempts=10, window_seconds=60)),
    ],
)
```
`routers/templates.py` (`/render`), `routers/sources/nautobot/ops.py` (`/{inventory_id}/analyze`):
add the `Depends(rate_limited(...))` entry to the route's `dependencies=[...]` (create the list if the
decorator has none). `routers/sources/ise/ops.py` (`APIRouter(` at l. 43) and
`routers/sources/batfish/query.py` (`APIRouter(` shown above): append the entry to the
router-level `dependencies` list.

### 6.3 Tests (write first)

| File | Test | Asserts |
|---|---|---|
| `test_rate_limit_dependency.py` (new) | `test_allows_up_to_budget_then_429`, `test_budget_is_per_user`, `test_429_has_retry_after`, `test_redis_down_falls_back_in_process` | |
| `test_service_factory.py` | `test_user_rate_limiter_is_cached_per_bucket` | same bucket → same object; different bucket → different |
| per router (`test_netmiko_router.py`, `test_git_operations_router.py`, `test_secret_manager_router.py`, `test_batfish_query_router_auth.py`, …) | `test_<endpoint>_is_rate_limited` | the route's dependency list contains the `rate_limited` dependency (inspect `route.dependant`) — avoids sleeping through real budgets |

### 6.4 Verification
`pytest tests/unit -k "rate or netmiko or secret_manager_router or batfish_query" --no-cov`; guards; ruff.
Manual: hit `/api/proxy/secret-manager/connections/<id>/test` 11× in a minute → the 11th returns 429.

---

## Phase 7 — Secret redaction and upload bounds (W6, W5/S15)

Files: `services/workflow_context/secret_fields.py`, `services/execution/step_runner/runner.py`,
`services/credentials/credentials_service.py`, `services/certificates/certificate_service.py`,
`core/config.py`, `main.py`, `docker/DOCKER.md`.
Depends on / conflicts: `credentials_service.py` is also edited in Phase 3 (different methods); `main.py` is
edited in Phases 3 and 8 (different blocks).

### 7.1 W6 — content-based redaction

Problem: `redact_secrets_in_data` recognises sealed envelopes and secret-looking *key names* only. A step
that unwraps a secret and copies it into a free-text field (a diff line, a log message, a command echo) is
persisted in `WorkflowStepResult.output` in clear.

Design: while a run segment executes, every cleartext secret that crosses a decrypt/unwrap boundary is
recorded in a per-segment set. `redact_secrets_in_data` then also replaces any exact occurrence of those
values (≥ 8 characters) in string leaves. The set lives in a `ContextVar` holding a *mutable* set created
at segment entry, so concurrent sibling steps (`asyncio.gather`) and `asyncio.to_thread` workers all
share it. Outside a run (API requests, scripts) nothing is recorded and behaviour is unchanged.

`backend/services/workflow_context/secret_fields.py`

before:
```python
from copy import deepcopy
from typing import Any

from core.crypto import EncryptionService

SEALED_MARKER = "__am_sealed__"
REDACTED_PLACEHOLDER = "***REDACTED***"
```
after:
```python
import functools
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from typing import Any, ParamSpec, TypeVar

from core.crypto import EncryptionService

SEALED_MARKER = "__am_sealed__"
REDACTED_PLACEHOLDER = "***REDACTED***"

# Shorter values (an "up", a port) would redact ordinary text and add no protection.
MIN_TRACKED_SECRET_LENGTH = 8

# Cleartext secrets seen while one run segment executes (W6). None outside a run.
_RUN_SECRETS: ContextVar[set[str] | None] = ContextVar("run_secrets", default=None)

_P = ParamSpec("_P")
_R = TypeVar("_R")


@contextmanager
def run_secret_scope():
    """Start (or join) a per-run-segment secret registry."""
    if _RUN_SECRETS.get() is not None:
        yield
        return
    token = _RUN_SECRETS.set(set())
    try:
        yield
    finally:
        _RUN_SECRETS.reset(token)


def with_run_secret_scope(fn: Callable[_P, Awaitable[_R]]) -> Callable[_P, Awaitable[_R]]:
    """Decorator form of :func:`run_secret_scope` for the step runner's async entry points."""

    @functools.wraps(fn)
    async def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        with run_secret_scope():
            return await fn(*args, **kwargs)

    return wrapper


def register_secret_value(value: str | None) -> None:
    """Remember a cleartext secret so later redaction can scrub it from free text."""
    registry = _RUN_SECRETS.get()
    if registry is not None and value and len(value) >= MIN_TRACKED_SECRET_LENGTH:
        registry.add(value)
```

before (`unwrap_secret`):
```python
    if is_sealed_secret(value):
        svc = encryption or EncryptionService()
        return svc.decrypt(str(value["ct"]).encode("ascii"))
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None
```
after:
```python
    if is_sealed_secret(value):
        svc = encryption or EncryptionService()
        cleartext = svc.decrypt(str(value["ct"]).encode("ascii"))
        register_secret_value(cleartext)
        return cleartext
    if isinstance(value, str):
        stripped = value.strip()
        register_secret_value(stripped)
        return stripped or None
    return None
```

before (`redact_secrets_in_data`, last lines):
```python
    cloned = deepcopy(data)
    _redact_inplace(cloned)
    return cloned
```
after:
```python
    cloned = deepcopy(data)
    _redact_inplace(cloned)
    known = _RUN_SECRETS.get()
    if known:
        # Longest first, so a secret that contains another is scrubbed whole.
        cloned = _scrub_known_values(cloned, sorted(known, key=len, reverse=True))
    return cloned
```
and add below `_redact_bag_paths`:
```python
def _scrub_known_values(node: Any, secrets: list[str]) -> Any:
    """Replace every exact occurrence of a known cleartext secret in string leaves (W6)."""
    if isinstance(node, str):
        for secret in secrets:
            if secret in node:
                node = node.replace(secret, REDACTED_PLACEHOLDER)
        return node
    if isinstance(node, dict):
        return {key: _scrub_known_values(value, secrets) for key, value in node.items()}
    if isinstance(node, list):
        return [_scrub_known_values(item, secrets) for item in node]
    return node
```
Update the "Limitation" paragraph of the `redact_secrets_in_data` docstring: a secret **unwrapped or
resolved from a credential during this run** is now also scrubbed from free text; a secret that never
passed through `unwrap_secret` / a credential decrypt (e.g. typed into a template by the author) is still
unknown to the redactor.

`backend/services/execution/step_runner/runner.py` — wrap the three entry points that hold a segment open.

before:
```python
from services.workflow_context.secret_fields import redact_secrets_in_data
...
    async def execute_all(self, *, run: WorkflowRun, workflow: Workflow) -> bool | FanOutSignal:
...
    async def resume_after_join(
...
    async def execute_subgraph(
```
after:
```python
from services.workflow_context.secret_fields import redact_secrets_in_data, with_run_secret_scope
...
    @with_run_secret_scope
    async def execute_all(self, *, run: WorkflowRun, workflow: Workflow) -> bool | FanOutSignal:
...
    @with_run_secret_scope
    async def resume_after_join(
...
    @with_run_secret_scope
    async def execute_subgraph(
```

`backend/services/credentials/credentials_service.py` — every decrypting read registers its result
(these three methods are the funnel for `CredentialManager`; confirm with
`grep -rn "_encryption.decrypt\|_read_vault_data" backend/services/credentials` before merging).

before (`get_decrypted_password`):
```python
            value = data.get("password") or data.get("token")
            if not value:
                raise CredentialMissingFieldError("Credential has no password")
            return value
        if not credential.password_encrypted:
            raise CredentialMissingFieldError("Credential has no password")
        return self._encryption.decrypt(credential.password_encrypted)
```
after:
```python
            value = data.get("password") or data.get("token")
            if not value:
                raise CredentialMissingFieldError("Credential has no password")
            register_secret_value(value)
            return value
        if not credential.password_encrypted:
            raise CredentialMissingFieldError("Credential has no password")
        password = self._encryption.decrypt(credential.password_encrypted)
        register_secret_value(password)
        return password
```
Same pattern for `get_decrypted_ssh_key` (the whole PEM) and `get_decrypted_ssh_passphrase`. Import:
`from services.workflow_context.secret_fields import register_secret_value` — check for an import cycle
(`secret_fields` imports only `core.crypto`; none expected).

### 7.2 W5 / S15 — bound uploads

`backend/services/certificates/certificate_service.py`

before:
```python
        safe_name = _sanitize_crt_filename(file.filename)
        content = await file.read()
```
after:
```python
        safe_name = _sanitize_crt_filename(file.filename)
        # A PEM certificate chain is a few KiB; refuse anything larger without buffering it (S15).
        content = await file.read(MAX_CERT_UPLOAD_BYTES + 1)
        if len(content) > MAX_CERT_UPLOAD_BYTES:
            raise ValueError(
                f"Certificate file is larger than {MAX_CERT_UPLOAD_BYTES // 1024} KiB"
            )
```
with `MAX_CERT_UPLOAD_BYTES = 64 * 1024` at module level. (The router already maps `ValueError` → 400.)

`backend/core/config.py` — next to `log_max_bytes`:
```python
        # Reject requests that announce a body larger than this (0 disables). A reverse proxy
        # should enforce its own limit too; this guards the direct-access / chunked-less case.
        self.max_request_body_bytes = self._get_int("MAX_REQUEST_BODY_BYTES", 25 * 1024 * 1024)
```
(declare `max_request_body_bytes: int` with the other attributes).

`backend/main.py` — after `domain_error_handler`:
```python
@app.middleware("http")
async def limit_request_body(request: Request, call_next):
    """413 for a declared Content-Length above MAX_REQUEST_BODY_BYTES (S15)."""
    limit = settings.max_request_body_bytes
    declared = request.headers.get("content-length")
    if limit and declared and declared.isdigit() and int(declared) > limit:
        return JSONResponse(status_code=413, content={"detail": "Request body too large"})
    return await call_next(request)
```
Chunked uploads without `Content-Length` are not covered — say so in `docker/DOCKER.md`, and add there a
"Request body size" paragraph recommending `client_max_body_size 25m;` (nginx) /
`maxRequestBodyBytes` (Traefik) in front of port 3000. Add `MAX_REQUEST_BODY_BYTES` to
`backend/.env.example`. Before merging, confirm the largest legitimate payload (CSV import, inventory
import, template upload) is below 25 MiB.

### 7.3 Tests (write first)

| File | Test | Asserts |
|---|---|---|
| `test_secret_fields.py` | `test_known_secret_scrubbed_from_free_text` | inside `run_secret_scope()`, `unwrap_secret(sealed)` then `redact_secrets_in_data({"msg": f"key={cleartext}!"})` → `msg == "key=***REDACTED***!"` |
| same | `test_short_values_are_not_tracked`, `test_no_scrub_outside_scope`, `test_longest_secret_replaced_first`, `test_scope_is_shared_with_threads_and_gathered_tasks` | |
| `test_credentials_service.py` | `test_decrypted_password_is_registered_in_scope` | |
| `test_step_runner_*.py` | `test_execute_all_runs_inside_secret_scope` | `_RUN_SECRETS.get()` is a set inside a step stub |
| `test_certificates_service.py` | `test_upload_over_64k_rejected`, `test_upload_exactly_64k_ok` | |
| `test_main_body_limit.py` (new) | `test_declared_oversize_body_413`, `test_limit_zero_disables` | |

### 7.4 Verification
`pytest tests/unit -k "secret or credentials or certificate or runner or body_limit" --no-cov`; guards; ruff.

---

## Phase 8 — Inventory ownership survives renames and deletes (S14 / R6)

Files: `repositories/inventory_repository.py`, `services/users/user_service.py`, `main.py`.
Depends on / conflicts: edits the same method `update_user` as Phase 1. Works without Phase 1, but only
Phase 1 closes the *self*-rename route to the same hole.

Decision revised after reading the code (replaces PD8): inventories are owned by username *string* in
~20 places (`InventoryRepository` queries, `InventoryService` access checks, `reference_resolver`). Adding an
`owner_user_id` FK would touch all of them plus a data back-fill. The vulnerability is only that an
orphaned `created_by` string can be inherited by a later holder of that username. Orphans arise from exactly
two events, both in `UserService`: **rename** and **delete**. So: carry private inventories along on
rename, remove them on delete, and warn about any pre-existing orphan. No schema change, no migration,
no API change. **Confirmed:** implement this variant now; the `owner_user_id` FK follow-up is tracked in `doc/OPEN_TODOS.md`
("Inventory ownership by user id"), added as part of Phase 8.

### 8.1 Repository helpers

`backend/repositories/inventory_repository.py` (add `delete, update` to the sqlalchemy import)

after the last method add:
```python
    def reassign_creator(self, old_username: str, new_username: str) -> int:
        """Point every inventory created by ``old_username`` at ``new_username`` (user rename).

        Flushes only; the caller commits, so the rename and the carry-over are one transaction (S14).
        """
        result = self.db.execute(
            update(Inventory)
            .where(Inventory.created_by == old_username)
            .values(created_by=new_username)
        )
        return result.rowcount or 0

    def delete_private_created_by(self, username: str) -> int:
        """Delete ``username``'s private inventories (user deletion). Global ones stay,
        with ``created_by`` kept as a display label. Flushes only; the caller commits."""
        result = self.db.execute(
            delete(Inventory).where(
                Inventory.scope == "private", Inventory.created_by == username
            )
        )
        return result.rowcount or 0

    def list_orphaned_private_creators(self, existing_usernames: set[str]) -> list[str]:
        """Distinct ``created_by`` values of private inventories whose owner no longer exists."""
        rows = self.db.scalars(
            select(distinct(Inventory.created_by)).where(Inventory.scope == "private")
        ).all()
        return sorted(name for name in rows if name not in existing_usernames)
```

### 8.2 `UserService` uses them in the same transaction

`backend/services/users/user_service.py`

before:
```python
class UserService:
    def __init__(self, db: Session) -> None:
        self._repo = UserRepository(db)
        self._rbac = RBACService(db)
```
after:
```python
class UserService:
    def __init__(self, db: Session) -> None:
        self._repo = UserRepository(db)
        self._rbac = RBACService(db)
        self._inventories = InventoryRepository(db)  # same Session => one transaction (S14)
```
(import `from repositories.inventory_repository import InventoryRepository`.)

before (`update_user`, last line):
```python
        return self._repo.update_user(user_id, **updates)
```
after:
```python
        if username is not None and target is not None and username != target.username:
            # S14: a private inventory must follow its owner to the new name, otherwise the old
            # name's next holder would inherit it. Flushed here, committed by update_user below.
            self._inventories.reassign_creator(target.username, username)
        return self._repo.update_user(user_id, **updates)
```
before (`delete_user`):
```python
        self._assert_can_remove(user_id, actor_user_id)
        return self._repo.delete_user(user_id)
```
after:
```python
        self._assert_can_remove(user_id, actor_user_id)
        target = self._repo.get_by_id(user_id)
        if target is not None:
            # S14: nobody may inherit this user's private inventories by taking the name later.
            self._inventories.delete_private_created_by(target.username)
        return self._repo.delete_user(user_id)
```
`UserRepository.update_user` / `delete_user` commit the shared session, so the carry-over/cleanup and the
user change succeed or fail together. If `reassign_creator` raises, nothing was committed.

### 8.3 Startup warning for rows that are already orphaned

`backend/main.py::lifespan`, inside the existing `with SessionLocal() as db:` block, after RBAC seeding:
```python
        orphaned = InventoryRepository(db).list_orphaned_private_creators(
            {user.username for user in UserRepository(db).list_users()}
        )
        if orphaned:
            logger.warning(
                "Private inventories exist for users that no longer exist: %s. "
                "Delete or reassign them (see doc/analysis/FABLE_MERGE_20261009.md S14).",
                ", ".join(orphaned),
            )
```
(imports: `InventoryRepository`, `UserRepository`; `UserRepository.list_users` already exists.)
Cleanup of existing orphans is manual: `DELETE FROM inventories WHERE scope='private' AND created_by NOT IN
(SELECT username FROM users);` — documented in the log line's doc reference, run by the operator after review.

### 8.4 Tests (write first)

| File | Test | Asserts |
|---|---|---|
| `test_user_service_inventories.py` (new, SQLite) | `test_rename_carries_private_and_global_inventories`, `test_rename_to_same_name_is_noop`, `test_delete_removes_private_keeps_global`, `test_new_holder_of_old_name_sees_nothing` | |
| `test_inventory_repository.py` | `test_list_orphaned_private_creators` | |
| `test_user_service_inventories.py` | `test_failed_user_update_rolls_back_inventory_reassignment` | patch `UserRepository.update_user` to raise → `created_by` unchanged after `db.rollback()` |
| `test_main_lifespan.py` / `caplog` | `test_orphan_warning_logged` | |

### 8.5 Verification
`pytest tests/unit -k "inventor or user_service" --no-cov`; guards (`check_router_repositories.py` must
still pass: no router touches the repository); ruff.

---

## Phase 9 — Code-quality hygiene (Q1–Q10, R7, T6, CI)

Pure maintenance. Every item is independent and can be its own commit; none changes API behaviour
except where stated. **Rule for the whole phase:** run the full unit suite before and after; a refactor
commit must not touch a test.

### 9.1 Q5 — say it when the cache is unavailable

`backend/service_factory.py`

before:
```python
    try:
        _cache_service = RedisCacheService(
            redis_url=settings.redis_url,
            key_prefix=settings.redis_key_prefix,
        )
        return _cache_service
    except Exception:
        return None
```
after:
```python
    global _cache_failure_logged
    try:
        _cache_service = RedisCacheService(
            redis_url=settings.redis_url,
            key_prefix=settings.redis_key_prefix,
        )
        _cache_failure_logged = False
        return _cache_service
    except Exception:
        # Callers degrade silently without a cache (OIDC login 503, no dedup, no repo lock):
        # make the cause visible once instead of on every call.
        if not _cache_failure_logged:
            logger.warning("Redis cache could not be created; running without it", exc_info=True)
            _cache_failure_logged = True
        return None
```
Add `_cache_failure_logged = False` next to `_cache_service`, and `logger = logging.getLogger(__name__)`
if the module has none. Test: two failing calls → one WARNING.

### 9.2 Q4 — no silent `except …: pass`

Policy: a swallowed exception either gets `logger.debug(..., exc_info=True)` (best-effort cleanup) or a
one-line comment saying why falling through is correct (expected parse fallback). One site is
security-relevant and gets a WARNING.

| Site | Action |
|---|---|
| `services/cache/redis_cache_service.py` l. 364, 386 | `logger.debug("Redis cleanup failed", exc_info=True)` |
| `services/auth/login_rate_limiter.py::clear` (l. 100) | `logger.debug("Could not clear rate-limit key", exc_info=True)` |
| `services/execution/run_input_validation.py` l. 75 | comment: `# not numeric: fall through to the string value` |
| `services/git/env.py` l. 45 | comment: `# unparseable URL: host stays "unknown" in the log line` |
| `services/git/file_service.py` l. 282, 284 | `logger.debug("History lookup failed for %s", path, exc_info=True)` |
| `services/git/config.py` l. 48, 53, 77, 85 | `logger.debug("git config read/restore failed", exc_info=True)` |
| `services/git/service.py` l. 260 (rmtree), 331, 448, 588 | l. 260: `logger.debug`. **l. 331/448/588 (restoring `origin` URL after a token URL was set): WARNING** |
| `services/git/debug_service.py` l. 133, 293 | `logger.debug` |
| `workflow_steps/run_command/exec_mode.py` l. 35 | comment: `# not JSON: keep the raw text` |
| `workflow_steps/config_to_attributes/executor.py` l. 249 | comment: `# non-numeric VLAN: leave the interface untagged_vlan unset` |

The security-relevant one, `services/git/service.py` (pull/push/fetch):

before:
```python
                finally:
                    if original_url:
                        try:
                            origin.set_url(original_url)
                        except Exception:
                            pass
```
after:
```python
                finally:
                    if original_url:
                        try:
                            origin.set_url(original_url)
                        except Exception:
                            # The credential-bearing URL may still be in .git/config (Q4).
                            # Never log the URL itself.
                            logger.warning(
                                "Could not restore remote URL for repository %s; "
                                ".git/config may still hold credentials",
                                repository.get("name"),
                                exc_info=True,
                            )
```
Prevent regressions: in `backend/pyproject.toml`
```toml
[tool.ruff.lint.flake8-bandit]
check-typed-exception = true   # S110/S112 also fire for `except ValueError: pass`
```
and add `# noqa: S110  # <reason>` to the comment-only sites above.

### 9.3 Q2 — one error-mapping decorator for the ISE router

New file `backend/routers/sources/ise/errors.py`:
```python
"""Exception → HTTP mapping shared by every ISE endpoint (Q2).

Replaces the 15 identical ``except ISENotFoundError / ISEValidationError / ISEAPIError /
HTTPException / Exception`` ladders in ``ops.py``.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable
from typing import ParamSpec, TypeVar

from fastapi import HTTPException, status

from core.safe_http_errors import raise_internal_server_error
from services.ise.common.exceptions import ISEAPIError, ISENotFoundError, ISEValidationError

logger = logging.getLogger(__name__)

_P = ParamSpec("_P")
_R = TypeVar("_R")


def ise_errors(action: str) -> Callable[[Callable[_P, Awaitable[_R]]], Callable[_P, Awaitable[_R]]]:
    """Map ISE failures to 404 / 400 / sanitised 502, anything else to a sanitised 500."""

    def decorator(fn: Callable[_P, Awaitable[_R]]) -> Callable[_P, Awaitable[_R]]:
        @functools.wraps(fn)
        async def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            try:
                return await fn(*args, **kwargs)
            except HTTPException:
                raise
            except ISENotFoundError as exc:  # subclass of ISEAPIError: must come first
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
            except ISEValidationError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
                ) from exc
            except ISEAPIError as exc:
                raise_internal_server_error(
                    logger,
                    f"ISE {action} failed: ",
                    exc,
                    status_code=status.HTTP_502_BAD_GATEWAY,
                )
            except Exception as exc:
                raise_internal_server_error(logger, f"Failed to {action}: ", exc)

        return wrapper

    return decorator
```
(`functools.wraps` keeps the signature, so FastAPI's dependency/parameter introspection is unchanged.)

`backend/routers/sources/ise/ops.py` — applied to each of the 15 handlers.

before:
```python
@router.get("/devices", response_model=ISENetworkDeviceListResponse)
async def list_devices(
    source_id: str,
    ...
) -> ISENetworkDeviceListResponse:
    device_service = _resolve_device_service(source_id, config)
    try:
        result = await device_service.list_devices(page=page, size=size, filter_=filter)
        search_result = result.get("SearchResult", {})
        return ISENetworkDeviceListResponse(...)
    except ISEValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ISEAPIError as exc:
        raise_internal_server_error(
            logger, "ISE list devices failed: ", exc, status_code=status.HTTP_502_BAD_GATEWAY
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to list ISE devices: ", exc)
```
after:
```python
@router.get("/devices", response_model=ISENetworkDeviceListResponse)
@ise_errors("list devices")
async def list_devices(
    source_id: str,
    ...
) -> ISENetworkDeviceListResponse:
    device_service = _resolve_device_service(source_id, config)
    result = await device_service.list_devices(page=page, size=size, filter_=filter)
    search_result = result.get("SearchResult", {})
    return ISENetworkDeviceListResponse(...)
```
Behaviour change to note in the commit: the 9 handlers that did not catch `ISENotFoundError` used to
answer 502 for a missing ISE object; they now answer 404 like the other six. `_resolve_credentials`
(which raises `HTTPException` before the `try`) is untouched. Leave `routers/sources/nautobot/ops.py`
alone unless its ladders are identical; if they are, add a sibling `nautobot/errors.py` the same way.
`check_http_500_leaks.py` must still pass (no `detail=str(...)` on a 5xx).

### 9.4 Q3 — inventory export/import out of the router

New file `backend/services/sources/nautobot/inventory_transfer.py`:
```python
"""Inventory export / import document format (version 2). Pure functions, no I/O."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

EXPORT_VERSION = 2


def build_export_document(inventory: dict[str, Any], *, exported_by: str) -> dict[str, Any]:
    tree: Any = None
    conditions = inventory.get("conditions", [])
    if conditions:
        first = conditions[0]
        if isinstance(first, dict) and first.get("version") == EXPORT_VERSION:
            tree = first.get("tree")
        else:
            tree = {
                "type": "root",
                "internalLogic": "AND",
                "items": [
                    {
                        "id": f"item-{index}",
                        "field": cond.get("field", ""),
                        "operator": cond.get("operator", ""),
                        "value": cond.get("value", ""),
                    }
                    for index, cond in enumerate(conditions)
                ],
            }
    return {
        "version": EXPORT_VERSION,
        "metadata": {
            "name": inventory["name"],
            "description": inventory.get("description", ""),
            "scope": inventory["scope"],
            "exportedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "exportedBy": exported_by,
            "originalId": inventory["id"],
        },
        "conditionTree": tree,
    }


def parse_import_document(document: dict[str, Any], *, created_by: str) -> dict[str, Any]:
    """Validate an exported document and return the ``create_inventory`` payload.

    Raises ``ValueError`` (→ HTTP 400) with the same messages the router used before.
    """
    if document.get("version") != EXPORT_VERSION:
        raise ValueError("Invalid inventory file format. Expected version 2.")
    if not document.get("conditionTree"):
        raise ValueError("Invalid inventory file. Missing condition tree.")
    metadata = document.get("metadata") or {}
    if not metadata.get("name"):
        raise ValueError("Invalid inventory file. Missing metadata.")
    return {
        "name": f"{metadata['name']} (imported)",
        "description": metadata.get("description", "Imported inventory"),
        "conditions": [{"version": EXPORT_VERSION, "tree": document["conditionTree"]}],
        "template_category": None,
        "template_name": None,
        "scope": "global",
        "created_by": created_by,
    }
```
`backend/routers/sources/nautobot/crud.py`

before (`export_inventory`, from `export_data = {` to the `return JSONResponse(`):
```python
        export_data = {
            "version": 2,
            "metadata": {...},
            "conditionTree": None,
        }

        conditions = inventory.get("conditions", [])
        if conditions:
            ...
        return JSONResponse(content=export_data, headers={...})
```
after:
```python
        export_data = build_export_document(inventory, exported_by=current_user.username)
        return JSONResponse(
            content=export_data,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="inventory-{inventory["name"]}.json"'
                )
            },
        )
```
before (`import_inventory`, from `import_data = request.import_data` to the `inventory_id = persistence.create_inventory({...})`):
```python
        import_data = request.import_data
        if import_data.get("version") != 2:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid inventory file format. Expected version 2.")
        ...
        inventory_id = persistence.create_inventory({...})
```
after:
```python
        payload = parse_import_document(request.import_data, created_by=current_user.username)
        inventory_id = persistence.create_inventory(payload)
```
(the existing `except ValueError` → 400 handler in the router already covers `parse_import_document`).
Tests: `test_inventory_transfer.py` for both functions (legacy flat conditions → tree, v2 passthrough,
each of the three import errors); existing router tests stay green.

### 9.5 Q6 — no blind `setattr` from `**kwargs`

New file `backend/repositories/updates.py`:
```python
"""Whitelisted attribute updates for repositories (Q6)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def apply_updates(obj: Any, values: Mapping[str, object], allowed: frozenset[str]) -> None:
    """Set ``values`` on ``obj``; refuse any key outside ``allowed``.

    Replaces ``if hasattr(obj, key): setattr(...)``, which silently accepts any attribute
    (including primary keys and relationship names) and silently drops typos.
    """
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ValueError(f"{type(obj).__name__}: fields not updatable: {', '.join(unknown)}")
    for key, value in values.items():
        setattr(obj, key, value)
```
`backend/repositories/user_repository.py`

before:
```python
        for key, value in kwargs.items():
            if value is not None and hasattr(user, key):
                setattr(user, key, value)
```
after:
```python
        apply_updates(
            user,
            {key: value for key, value in kwargs.items() if value is not None},
            _UPDATABLE_FIELDS,
        )
```
with, at module level:
```python
_UPDATABLE_FIELDS = frozenset(
    {
        "username", "password_hash", "is_active", "must_change_password", "token_version",
        "email", "display_name", "oidc_provider", "oidc_subject",
    }
)
```
`backend/repositories/rbac_repository.py::update_role`: allowed = `{"name", "description"}`.
Remaining repositories (`credentials`, `inventory`, `schedule`, `templates`, `workflow`, `base`): the
allowed set is exactly the keys their service passes. Derive it mechanically: `grep -n "repo.update\|_repo.update\|repository.update" -A12`
in the owning service, list the keyword names, put them in a module-level frozenset, replace the loop.
Before merging each, run that domain's tests; an unexpected key now fails loudly (that is the point).
Add `tests/unit/test_apply_updates.py` (unknown key → `ValueError`, allowed key set, empty mapping no-op).

### 9.6 Q8 — one way to write a repository

Decision: **keep** `BaseRepository` (git and secret-manager repositories use it) but make it consistent.
Collapse the duplicated "session given / not given" bodies and drop legacy `Query`.

`backend/repositories/base.py` — replace from `get_by_id` to the end of the class:

before:
```python
    def get_by_id(self, id: int, db: Session | None = None) -> T | None:
        with self._db_session(db) as s:
            return s.query(self.model).filter(self.model.id == id).first()
    ...
    def create(self, db: Session | None = None, **kwargs) -> T:
        if db is not None:
            obj = self.model(**kwargs)
            db.add(obj)
            db.commit()
            db.refresh(obj)
            return obj

        with self._db_session() as s:
            obj = self.model(**kwargs)
            ...
```
after:
```python
    def get_by_id(self, id: int, db: Session | None = None) -> T | None:
        with self._db_session(db) as s:
            return s.get(self.model, id)

    def get_all(self, db: Session | None = None) -> list[T]:
        with self._db_session(db) as s:
            return list(s.scalars(select(self.model)))

    def create(self, db: Session | None = None, **kwargs) -> T:
        # _db_session yields the caller's session as-is (not closed) or opens/closes one.
        with self._db_session(db) as s:
            obj = self.model(**kwargs)
            s.add(obj)
            s.commit()
            s.refresh(obj)
            return obj

    def update(self, id: int, db: Session | None = None, **kwargs) -> T | None:
        with self._db_session(db) as s:
            obj = s.get(self.model, id)
            if obj is not None:
                apply_updates(obj, kwargs, self.updatable_fields)
                s.commit()
                s.refresh(obj)
            return obj

    def delete(self, id: int, db: Session | None = None) -> bool:
        with self._db_session(db) as s:
            obj = s.get(self.model, id)
            if obj is None:
                return False
            s.delete(obj)
            s.commit()
            return True

    def filter(self, db: Session | None = None, **kwargs) -> list[T]:
        with self._db_session(db) as s:
            stmt = select(self.model)
            for key, value in kwargs.items():
                if hasattr(self.model, key):
                    stmt = stmt.where(getattr(self.model, key) == value)
            return list(s.scalars(stmt))

    def count(self, db: Session | None = None) -> int:
        with self._db_session(db) as s:
            return s.scalar(select(func.count()).select_from(self.model)) or 0

    def exists(self, id: int, db: Session | None = None) -> bool:
        with self._db_session(db) as s:
            return s.get(self.model, id) is not None
```
with `from sqlalchemy import func, select`, `from repositories.updates import apply_updates`, and on the class
`updatable_fields: frozenset[str] = frozenset()` that subclasses override (`GitRepositoryRepository`:
the `GitRepositoryService.update_repository` keys incl. `webhook_secret_encrypted`;
`SecretManagerConnectionRepository`: `{"name","backend","credential_name","verify_ssl","is_active","backend_config","description","updated_at"}`
— exactly `valid_fields` in `connection_service.update_connection`).
The 8 remaining `s.query(...)` calls in `repositories/git/git_repository_repository.py` and
`repositories/secret_manager/secret_manager_connection_repository.py` become `select()`:

before:
```python
            return s.query(GitRepository).filter(GitRepository.name == name).first()
...
            return s.query(GitRepository).filter(GitRepository.name == name).count() > 0
```
after:
```python
            return s.scalar(select(GitRepository).where(GitRepository.name == name))
...
            return s.scalar(select(func.count()).select_from(GitRepository).where(GitRepository.name == name)) > 0
```
(`get_by_id_fresh` keeps `populate_existing`: `s.scalar(select(...).where(...).execution_options(populate_existing=True))`.)
Tests: the existing repository/service tests cover behaviour; add one `test_base_repository.py` against
in-memory SQLite (CRUD + `update` with a disallowed key raises).

### 9.7 Q9 — type-check baseline and `GitRepository` as `Mapped`

Measured today (`pyright 1.1.406`, basic): **73 errors** — not the 158 in the old analysis. Largest files:
`services/git/repository_service.py` 11, `services/cache/redis_cache_service.py` 8,
`repositories/base.py` 6 (fixed by §9.6), `services/git/connection.py` 5. The first and third come from
`GitRepository` still using classic `Column(...)` (`SecretManagerConnection` is already `Mapped`).

`backend/core/models/git.py` — convert to `Mapped[...]` (no schema change; same types and defaults, so
`AutoSchemaMigration` sees no diff):

before:
```python
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False)
    category = Column(String(50), nullable=False)
    ...
    credential_name = Column(String(255))
    ...
    webhook_secret_encrypted = Column(LargeBinary)
    webhook_auto_deploy = Column(Boolean, nullable=False, default=False)
```
after:
```python
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    branch: Mapped[str] = mapped_column(String(255), nullable=False, default="main")
    auth_type: Mapped[str] = mapped_column(String(50), nullable=False, default="token")
    credential_name: Mapped[str | None] = mapped_column(String(255))
    path: Mapped[str | None] = mapped_column(String(1000))
    verify_ssl: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    git_author_name: Mapped[str | None] = mapped_column(String(255))
    git_author_email: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_sync: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_status: Mapped[str | None] = mapped_column(String(255))
    webhook_secret_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    webhook_auto_deploy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
```
(imports: `from datetime import datetime`, `from sqlalchemy.orm import Mapped, mapped_column`; drop `Column`.)
Then re-run `pyright`, fix the remainder file by file (mostly `str | None` narrowing), record the new
count in `doc/OPEN_TODOS.md`, and pin a newer `pyright` in `requirements-dev.txt`
(the installed launcher asks for 1.1.414+; re-baseline after bumping).

### 9.8 Q7 — strict request models, enforced by a test

1. New `backend/tests/unit/test_request_models_forbid_extra.py`:
```python
"""Every request model rejects unknown fields (Q7). Shrink LEGACY_LENIENT; never grow it."""

import importlib
import inspect
import pkgutil

from pydantic import BaseModel

import models

SUFFIXES = ("Request", "Create", "Update")
LEGACY_LENIENT: set[str] = {...}  # fill from the first red run of this test, one entry per class


def _request_models():
    for info in pkgutil.iter_modules(models.__path__):
        module = importlib.import_module(f"models.{info.name}")
        for name, cls in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(cls, BaseModel)
                and cls.__module__ == module.__name__
                and name.endswith(SUFFIXES)
            ):
                yield f"{module.__name__}.{name}", cls


def test_request_models_forbid_extra():
    lenient = {
        key for key, cls in _request_models() if cls.model_config.get("extra") != "forbid"
    }
    assert lenient == LEGACY_LENIENT, sorted(lenient ^ LEGACY_LENIENT)
```
2. Convert one domain per commit: add `model_config = ConfigDict(extra="forbid")`, delete the names from
`LEGACY_LENIENT`, then check the frontend payload for that domain (`grep -rn "apiCall('<route>'" frontend/src`,
compare the sent keys with the model) and run `npm run build` plus that domain's flow in the browser; an
extra key the UI sends today must be removed from the UI payload (or added to the model) in the same commit.
Order: credentials → git repositories → workflows/runs → templates → sources → settings → the rest.
Already strict (leave as is): the auth/user models from the S4/S6 work and, after Phase 4, the secret-manager models.

### 9.9 R7 — one query instead of 2N for the role path

`backend/repositories/rbac_repository.py` (add `exists` to the sqlalchemy import)

after `get_role_permissions`:
```python
    def user_has_permission_via_roles(self, user_id: int, permission_id: int) -> bool:
        """True when any role of the user grants ``permission_id`` (one EXISTS query)."""
        return bool(
            self.db.scalar(
                select(
                    exists().where(
                        UserRole.user_id == user_id,
                        RolePermission.role_id == UserRole.role_id,
                        RolePermission.permission_id == permission_id,
                        RolePermission.granted.is_(True),
                    )
                )
            )
        )
```
`backend/services/auth/rbac_service.py::has_permission`

before:
```python
        for role in self._repo.get_user_roles(user_id):
            if any(p.id == permission.id for p in self._repo.get_role_permissions(role.id)):
                return True

        return False
```
after:
```python
        return self._repo.user_has_permission_via_roles(user_id, permission.id)
```
(`RolePermission.granted.is_(True)` also removes one of the three remaining `# noqa: E712`.) Result: 3 queries
per permission check regardless of role count (permission lookup, override, EXISTS). Not changed on purpose:
the second `User` load per request (`require_permission` calls `_load_active_user` separately from
`get_current_user`) — folding them needs a reshaping of the security-critical dependency chain for a small
gain; revisit only if profiling shows it. Tests: existing `test_rbac_service.py` precedence cases must pass
unchanged; add `test_user_with_two_roles_one_granting` and `test_role_permission_granted_false_is_not_a_grant`.

### 9.10 T6 — a way to bind an IdP identity to an existing account

Decision: an admin CLI, not an API (identity binding is a rare, sensitive, break-glass operation, and
P3-style gating of a new endpoint is more surface than it is worth).

new — `backend/scripts/link_oidc_identity.py`
```python
#!/usr/bin/env python3
"""Bind an existing local user to an IdP identity.

    python scripts/link_oidc_identity.py <username> <provider_id> <subject>

An OIDC login only ever matches on (oidc_provider, oidc_subject) -- never on username -- so
this is the only way to let an existing local account sign in through SSO. Run it deliberately.
"""

from __future__ import annotations

import sys

from core.database import SessionLocal
from repositories.user_repository import UserRepository


def main(username: str, provider_id: str, subject: str) -> int:
    with SessionLocal() as db:
        users = UserRepository(db)
        user = users.get_by_username(username)
        if user is None:
            print(f"No such user: {username}", file=sys.stderr)
            return 1
        holder = users.get_by_oidc_identity(provider_id, subject)
        if holder is not None and holder.id != user.id:
            print(f"Identity already bound to user '{holder.username}'", file=sys.stderr)
            return 1
        users.update_user(
            user.id,
            oidc_provider=provider_id,
            oidc_subject=subject,
            token_version=user.token_version + 1,  # end existing sessions
        )
        print(f"Linked {username} to {provider_id}:{subject}")
        return 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(*sys.argv[1:]))
```
(Whitelist: add `oidc_provider`/`oidc_subject` — already in `_UPDATABLE_FIELDS` from §9.5.) Document it in
`doc/claude/auth.md` under "OIDC Identity Binding". Test: `test_link_oidc_identity.py` (links, refuses a
bound identity, refuses an unknown user).

### 9.11 Q1 / Q10 — long functions and God objects (bounded, characterisation first)

This is the one item where exact before/after cannot be quoted usefully: the change is a pure move of
100–250 lines, and the right cut points are only visible with the function open. The plan therefore fixes
the **method and the acceptance criteria** instead of pasting the functions.

Targets (the five worst, by measured length): `workflow_steps/configure_replace_config/executor.py::_process_one_device` (257),
`workflow_steps/undefined_and_unused/executor.py::execute` (200),
`workflow_steps/compare_pyats_snapshot/executor.py::_compare_one_device` (181),
`workflow_steps/common/git_workflow_step.py::run_git_workflow_step` (158),
`workflow_steps/open_change_request/executor.py::execute` (154).

Method for each, in its own commit:
1. Characterisation: if the function's branches are not all covered by `tests/unit/test_<step>*.py`, add tests
   for the uncovered outcomes first (success, each failure code, skip paths). They must pass on the
   *unmodified* code.
2. Extract phases as module-level functions with explicit inputs and a small frozen dataclass result, e.g.
   for `_process_one_device`:
```python
@dataclass(frozen=True)
class _DeviceResult:
    device: DeviceContext
    outcome: str            # "success" | "failure" | "skipped"
    error: DeviceError | None = None

async def _backup_running_config(...) -> _BackupResult: ...
async def _upload_candidate(...) -> _UploadResult: ...
async def _apply_replace(...) -> _ReplaceResult: ...
async def _verify_and_rollback(...) -> _VerifyResult: ...

async def _process_one_device(...) -> _DeviceResult:      # <= 40 lines: call the phases in order,
    ...                                                   # return early on the first failed phase
```
3. The original function keeps its signature; callers and tests are untouched.
4. Acceptance: function ≤ 50 lines, each extracted phase ≤ 60, no behaviour or log-message change, the
   full unit suite green with no test edited (new characterisation tests excepted).

Q10 (`DeviceCommonService` 43 pass-throughs, `InterfaceManagerService`, `DeviceUpdateService.update_device`
149, `GitService.push`) follows the same method; do them only when a feature already needs to touch the file.
Not planned: renaming services to `{domain}_service.py` (Q11) — cosmetic.

### 9.12 CI — restore (decided)

`.github/workflows/backend-ci.yml` was deleted deliberately in `777c071`, so **there is currently no CI**
(the 09-02/09-12 analyses and `CLAUDE.md` still describe one). Either:
- **Restore** (**decided 2026-10-09**; do it before going public): `git show 58f1ce4:.github/workflows/backend-ci.yml >
  .github/workflows/backend-ci.yml`, then `git show 21b1f64` for the action-version bump; keep pyright
  advisory until §9.7 brings it to 0; or
- ~~Leave removed~~ (not chosen) — would delete the "CI runs these" sentences from `CLAUDE.md` / `doc/claude/development.md`.
Run the equivalent locally either way: ruff, the four guard scripts, `pytest tests/unit`,
`pip-audit -r requirements.txt -r requirements-dev.txt --ignore-vuln PYSEC-2026-2858`, `pyright`.

### 9.13 Verification
After each commit: `ruff check` on touched files, `pytest tests/unit --no-cov -q`, the four guard scripts.
After the phase: full `pytest tests/unit` (coverage ratchet 81 %), `pyright` count recorded.

---

## Phase 10 — Documentation and repository hygiene (D1–D7, T5)

Pure docs plus one new file; no code. Do this phase early — D1 and D2 are the cheapest items in the plan.

### 10.1 D1 — `SECURITY.md` (new, repo root)

```markdown
# Security Policy

## Reporting a vulnerability

Please do not open a public issue. Report privately via GitHub's "Report a vulnerability" button
(Security → Advisories) or e-mail <security contact>. Include the affected version/commit, steps to
reproduce and the impact. You will get an acknowledgement within 5 working days.

## Supported versions

Only the latest commit on `main` is supported; fixes are not back-ported.

## Scope and deployment assumptions

Auxilium Manus is an internal NetDevOps tool. It assumes:
- the backend is reachable only through the bundled Next.js proxy (`/api/proxy/*`);
- a TLS-terminating reverse proxy sits in front of port 3000 and sets `X-Forwarded-For`;
- `ENV=production`, with the secrets required by `docker/.env.example` set.

## Accepted risks

Documented, with reasoning, in `doc/SECURITY-NOTES.md`: optional TLS verification opt-out for
development sources, Netmiko without SSH host-key checking, git credentials visible in process
argv for the duration of a clone/push, and raw device configurations uploaded to the configured
Batfish coordinator. Reports about these are welcome but are known and by design.

## Hardening reference

`doc/analysis/FABLE_BACKEND_*.md` record the audits performed and what was fixed.
```
Fill in the real contact before publishing. Link it from `README.md`.

### 10.2 D2 — `CLAUDE.md` and `doc/claude/database.md`

`CLAUDE.md` l. 29

before: `- **PostgreSQL single database** with 15 tables (10 domain + 5 RBAC), defined in `/backend/core/models/``
after: `- **PostgreSQL single database** (26 tables, 5 of them RBAC), defined in `/backend/core/models/`; the list lives in `doc/claude/database.md`, not here`
(26 = `grep -c __tablename__ backend/core/models/*.py`, summed; re-count when you edit.)

`CLAUDE.md` "Backend Core" list — before ends at `/backend/main.py`; after add:
```
- `/backend/core/production_guards.py` — refuses unsafe config outside `ENV=development`
- `/backend/core/safe_urls.py`, `safe_hosts.py` — outbound URL / Netmiko host policy (SSRF)
- `/backend/core/client_ip.py` — trusted-proxy client IP resolution
- `/backend/core/rate_limit.py` — `rate_limited(...)` per-user dependency (Phase 6)
- `/backend/core/vault.py`, `/backend/services/vault/` — OpenBao client; `/backend/services/secret_manager/` — Secret Manager connections
- `/backend/core/dev_tools.py` — `ENABLE_DEV_TOOLS` gate
```
`doc/claude/database.md` "Domain tables" block and "Model File Locations" table: regenerate from
`ls backend/core/models` — add `background_tier`, `notifications`, `schedules`, `user_preferences`,
`workflow_changes`, `secret_manager`, `catalyst_center`/whatever else is present; one row per file.

### 10.3 D3 — remove the dangling `doc/FABLE-ANALYSIS.md` references (10 hits)

The section numbers refer to a deleted document, so repointing would be wrong; delete the clause.

| File:line | before | after |
|---|---|---|
| `services/auth/auth_service.py:86` | `…doc/FABLE-ANALYSIS.md §4.1).` | drop the parenthetical, keep the sentence |
| `services/execution/graph.py:8` | `doc/FABLE-ANALYSIS.md §4.2 and §5.3.` | delete the sentence |
| `services/workflow/workflow_service.py:47` | `See doc/FABLE-ANALYSIS.md §4.2: without this, a cyclic graph…` | `Without this, a cyclic graph…` |
| `services/settings/exceptions.py:6` | `See doc/FABLE-ANALYSIS.md §3.1.` | delete |
| `services/settings/settings_service.py:123` | `-- see doc/FABLE-ANALYSIS.md 3.1.` | delete |
| `tests/unit/test_require_permission_inactive_user.py:2` | `— see FABLE-ANALYSIS.md §4.3.` | delete |
| `tests/unit/test_update_nautobot_device_helpers.py:2` | `— see doc/FABLE-ANALYSIS.md §5.2 and §7.` | delete |
| `tests/unit/test_execution_graph.py:2`, `test_workflow_service_graph_validation.py:2` | `See doc/FABLE-ANALYSIS.md §…` | delete |
| `doc/SECURITY-NOTES.md:3` | `…from `doc/FABLE-ANALYSIS.md` §4.7 that were reviewed…` | `…from the 2026 security reviews (`doc/analysis/FABLE_BACKEND_*.md`) that were reviewed…` |

Verify: `grep -rn "FABLE-ANALYSIS" backend doc --include='*.py' --include='*.md' | grep -v "doc/analysis\|doc/plans"` → empty.

### 10.4 D4 — `doc/SECURITY-NOTES.md` stale path

before (l. 42): `` `services/sources/git/git_source_service.py` embeds HTTP basic-auth credentials into the remote URL (`_build_auth_url`) and passes that URL directly in the `git clone`/`git push` argv (`subprocess.run(cmd, ...)`) ``
after: `` `services/git/auth.py::build_auth_url` embeds HTTP basic-auth credentials into the remote URL, and `services/git/service.py` passes that URL to GitPython (`Repo.clone_from`, `origin.pull/push`), i.e. in the `git` subprocess argv ``
Re-read the rest of that paragraph for `_redact_secrets` references and point it at the current redaction
helper (`grep -rn "redact" backend/services/git`).

### 10.5 D5 — Batfish doc status line

`doc/BATFISH_INTEGRATION.md` l. 148–150

before:
```
**Implemented.** Everything below exists on `feature/batfish` (as of this
writing, not yet merged to `main` — check `git status`/`git log` for current
branch/commit state rather than trusting this document's staleness).
```
after:
```
**Implemented and merged to `main`.**
```

### 10.6 D6 — INSTALL and request-body limits

`INSTALL.md`: in the infrastructure section add a line "Optional: OpenBao-backed credential storage —
see [`doc/VAULT_INTEGRATION.md`](doc/VAULT_INTEGRATION.md) (production setup) and
`docker/openbao/` (development only)." `docker/DOCKER.md`: add a "Request body size" paragraph (see Phase 7 §7.2).

### 10.7 D7 — before flipping the repository to public

Checklist, run once on the final tree: `gitleaks detect --no-git` and `gitleaks detect` (history);
`git log --all -- '*.env' '*oidc_providers.yaml'` is empty; decide whether `routers/git/debug.py` stays
(it is dev-tools gated and returns 404 in production; keeping it is fine, say so in `SECURITY.md` if asked);
confirm `SECURITY.md` has a real contact; confirm §9.12 (CI) is decided.

### 10.8 T5 — document, do not change, the logout semantics

Logging out ends **every** session of that user on every device (`token_version` bump). That is the
conservative property the design chose; per-session logout would add a Redis lookup to every request.
Add one sentence to `doc/claude/auth.md` ("Revocation") and to the logout confirmation text in the
frontend profile menu ("This signs you out everywhere."). `jti` stays minted for a future denylist.

### 10.9 Verification
`grep` checks above; render `SECURITY.md`/`INSTALL.md` links; no code touched, so no test run is needed
beyond `ruff check` for the docstring edits in §10.3.

---

## Order of work and effort

| Order | Phase | Effort | Notes |
|---|---|---|---|
| 1 | 10 (docs, `SECURITY.md`) | 0.5 day | no risk; unblocks going public |
| 2 | 1 (account/RBAC guards) | 0.5 day | check the admin user dialog for PD1 |
| 3 | 2 (webhook/git lock) | 0.5 day | |
| 4 | 3 (OpenBao) | 1 day | needs the dev OpenBao for the opt-in integration run |
| 5 | 4 (Secret Manager) | 1 day + Infisical session | §4.5 needs a running Infisical |
| 6 | 5 (Batfish) | 0.5 day | |
| 7 | 6 (rate limiting) | 0.5 day | |
| 8 | 7 (redaction, uploads) | 1 day | check the 25 MiB default against real imports |
| 9 | 8 (inventory ownership) | 0.5 day | |
| 10 | 9 (quality) | 3–4 days, splittable | 9.11 is open-ended; time-box it |

## Definition of done (every phase)

- [ ] Tests listed in the phase exist, were red before the change, and pass.
- [ ] `ruff check` clean on touched files; `check_asyncio_run.py`, `check_http_500_leaks.py`,
      `check_router_repositories.py`, `check_text_sql.py` all pass.
- [ ] `pytest tests/unit` green with coverage ≥ 81 %.
- [ ] `doc/analysis/FABLE_MERGE_20261009.md`: the phase's findings get a "Fixed (commit)" status.
- [ ] Docs named in the phase updated (`CLAUDE.md`, `doc/VAULT_INTEGRATION.md`, `doc/SECRET_MANAGER_INTEGRATION.md`, …).
