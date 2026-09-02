# Plan: Fix the four release-blocking backend issues

Source: `doc/analysis/FABLE_BACKEND_20260902.md` §5.3, findings S1, S2+S3, S4, S6.
Status: proposed, 2026-09-02. Review findings from `doc/plans/FABLE_BACKEND_QUESTIONS.md`
folded in on 2026-09-02 (see §0.1). Nothing in this document has been implemented yet.

| # | Issue | Clarity | Needs a decision? |
|---|---|---|---|
| 1 | OIDC account takeover by username (S1) | Clear | D1 only (legacy rows) |
| 2 | `users:write` escalates to admin; system roles renamable (S2, S3) | Clear mechanics, one policy choice | **D2** (delegation model) |
| 3 | Docker runs as root with development defaults (S4) | Clear | **D3** (runtime CA install) |
| 4 | No password policy, no self-service change (S6) | Clear | D4, D5 (limits, enforcement point) |

Each decision below has a recommended default. If you accept the defaults, the code in this
document is the code to write. Every issue ends with the tests that must exist before the fix is
considered done, following the TDD rule in `~/.claude/rules/common/testing.md`.

---

## 0. Decisions to confirm

**D1 — Existing OIDC users without a stored subject.**
The app is not public, so no production rows exist. Recommended: do **not** write backfill or
trust-on-first-use code. Existing OIDC-provisioned test users are deleted and re-provisioned.
Alternative (if you have OIDC users you want to keep): bind the subject on the first successful
login *only* when the row already has `oidc_provider == provider_id`, and log it at WARNING.

**D2 — Who may grant what (delegation model).** Two workable models:

- *(a) Admin-only for security resources.* Any grant, override, or role change that touches
  `rbac.*`, `users:*`, `system.*` requires the `admin` role. Everything else stays as today.
  Simple, small diff, but a `users:write` holder can still self-grant e.g. `credentials:reveal`.
- *(b) Delegation bound (recommended).* An actor may only grant what they themselves hold, may
  never modify their own account, and admin is required for the protected resources in (a) and
  for touching any user who holds `admin`. This is the standard "no privilege amplification" rule
  and closes every path found in the analysis.

The plan below implements (b). Choosing (a) removes `_assert_actor_holds` and the self-target
check from §2 and keeps everything else.

**D3 — Runtime CA certificate installation in containers.** `INSTALL_CERTIFICATE_FILES=true`
and `POST /certificates/add-to-system` copy into `/usr/local/share/ca-certificates` and run
`update-ca-certificates`, which needs root. Options:

- *(a) Root entrypoint that drops privileges (recommended).* `start.sh` runs as root, installs
  certs, fixes `/app/data` ownership, then `exec setpriv --reuid=manus ...`. The application
  processes never run as root. `add-to-system` stays dev-tools-gated and will fail with the
  existing "permission denied" response in production, which is acceptable.
- *(b) Build-time certs only.* `USER manus` in the Dockerfile, remove runtime install, document
  `docker/certs/` (already supported by `Dockerfile.basic`). Simplest image, but private-CA
  changes require a rebuild.

**D4 — Password limits.** Recommended: minimum 12 characters, maximum 128 (bcrypt/argon2 safe),
reject the username and a short built-in denylist. No composition rules (NIST 800-63B).

**D5 — Where `must_change_password` is enforced.** Recommended: backend, in `core/auth.py`, so
an API client cannot skip it; the frontend redirect is a convenience on top. Alternative:
frontend-only redirect (smaller change, weaker).

### 0.1 Review resolutions (2026-09-02)

The review in `doc/plans/FABLE_BACKEND_QUESTIONS.md` found four gaps. Each is resolved below and
the affected section has been rewritten; this table is the index.

| # | Gap | Resolution | Section |
|---|---|---|---|
| R1 | `docker/.env.example` already exists as a stale copy of `backend/.env.example`; compose comment says "not via docker/.env" | **Repurpose** the existing file as the compose secrets template (it is already what `start-docker.sh` and `docker/README.md` copy to `.env`). Strip values, fix the compose comment, stop the auto-copy. | §3.5 |
| R2 | Seeded admin bypasses the password policy (`ensure_initial_admin` never calls `validate_password`; guard only rejects the literal `admin`) | Length check on `INITIAL_PASSWORD` in `production_guards.py` (runs outside development only, so dev `admin/admin` keeps working and is covered by the forced change). | §3.6, §4.4 |
| R3 | `useApi` throws on 403 before reading the body and cannot open a dialog | Parse the 403 body; on `code == "password_change_required"` flip `must_change_password` on the user already held in `useAuthStore`; a dialog mounted in `DashboardShell` watches that flag. No new store. | §4.7 |
| R4 | Three auth response parsers, plan named two | All three listed (`login`, `refresh`, `me`). | §4.7 |
| R5 | Smaller: §1.6 needs response fields; §2.4 `update_user` restructuring understated; repository `**kwargs` pattern is being extended | Noted inline. | §1.6, §2.4 |

---

## 1. OIDC: bind identities by `(provider, sub)`, never auto-link by username

### 1.1 Problem in one sentence

`OIDCService.provision_or_get_user` looks the user up by the `preferred_username` claim and, if
the row exists and is active, overwrites `oidc_provider` and returns it — so an IdP identity
with `preferred_username=admin` logs in as the local `admin`.

### 1.2 Data model

`backend/core/models/users.py` — before:

```python
    oidc_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
```

after:

```python
    oidc_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Stable subject identifier issued by the IdP (the `sub` claim). Together with
    # oidc_provider this is the only key an OIDC login may match an existing user on.
    oidc_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        Index(
            "uq_users_oidc_identity",
            "oidc_provider",
            "oidc_subject",
            unique=True,
            postgresql_where=text("oidc_subject IS NOT NULL"),
        ),
    )
```

Add `Index` and `text` to the `sqlalchemy` import. The auto-schema sync adds the column and the
index on next start (`doc/MIGRATION_SYSTEM.md`: missing columns and indexes always apply).

### 1.3 Repository

`backend/repositories/user_repository.py` — add:

```python
    def get_by_oidc_identity(self, provider_id: str, subject: str) -> User | None:
        return self.db.scalar(
            select(User).where(
                User.oidc_provider == provider_id,
                User.oidc_subject == subject,
            )
        )
```

and extend `create_user(...)` with `oidc_subject: str | None = None` passed through to `User(...)`.

### 1.4 Service

`backend/services/auth/oidc_service.py`.

New exception next to the existing ones:

```python
class OIDCIdentityConflictError(RuntimeError):
    """Raised when the IdP username collides with a local account that this
    OIDC identity is not bound to. Never auto-link — an IdP-controlled claim
    must not be able to select an existing local account."""
```

`extract_user_data` — before:

```python
        return {
            "username": username,
            "email": claims.get(mappings["email"]),
            "display_name": claims.get(mappings["name"]),
            "sub": claims.get("sub"),
            "provider_id": provider_id,
        }
```

after (`sub` is mandatory in OIDC Core §2; refuse tokens without it):

```python
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise OIDCError(f"ID token from provider '{provider_id}' has no 'sub' claim")

        return {
            "username": username,
            "email": claims.get(mappings["email"]),
            "display_name": claims.get(mappings["name"]),
            "sub": subject,
            "provider_id": provider_id,
        }
```

`provision_or_get_user` — before:

```python
        existing = users.get_by_username(username)
        if existing is not None:
            updates: dict[str, Any] = {}
            if user_data.get("email") and existing.email != user_data["email"]:
                updates["email"] = user_data["email"]
            if user_data.get("display_name") and existing.display_name != user_data["display_name"]:
                updates["display_name"] = user_data["display_name"]
            if existing.oidc_provider != provider_id:
                updates["oidc_provider"] = provider_id

            if updates:
                existing = users.update_user(existing.id, **updates) or existing

            if not existing.is_active:
                raise OIDCApprovalPendingError(username, existing.email, provider_id)

            return existing

        if not provider.get("auto_provision", True):
            raise OIDCAutoProvisioningDisabledError(...)

        random_password = secrets.token_urlsafe(32)
        new_user = users.create_user(
            username=username,
            password_hash=password_hash.hash(random_password),
            is_active=False,
            email=user_data.get("email"),
            display_name=user_data.get("display_name"),
            oidc_provider=provider_id,
        )
```

after:

```python
        subject: str = user_data["sub"]

        # 1. The only path that returns an existing user: exact identity match.
        existing = users.get_by_oidc_identity(provider_id, subject)
        if existing is not None:
            existing = self._sync_profile(users, existing, user_data)
            if not existing.is_active:
                raise OIDCApprovalPendingError(username, existing.email, provider_id)
            return existing

        # 2. Username collision with a row this identity is not bound to.
        #    Local accounts, accounts from another provider, and accounts from the
        #    same provider with a different subject are all refused. (D1: no TOFU.)
        if users.get_by_username(username) is not None:
            logger.warning(
                "OIDC login refused: provider=%s username collides with an existing account",
                provider_id,
            )
            raise OIDCIdentityConflictError(
                "This identity cannot be linked to an existing account; "
                "ask an administrator"
            )

        # 3. New user, provisioned inactive exactly as before.
        if not provider.get("auto_provision", True):
            raise OIDCAutoProvisioningDisabledError(...)

        random_password = secrets.token_urlsafe(32)
        new_user = users.create_user(
            username=username,
            password_hash=password_hash.hash(random_password),
            is_active=False,
            email=user_data.get("email"),
            display_name=user_data.get("display_name"),
            oidc_provider=provider_id,
            oidc_subject=subject,
        )
```

with the helper:

```python
    @staticmethod
    def _sync_profile(users: UserRepository, user: User, user_data: dict[str, Any]) -> User:
        """Refresh email/display_name from the IdP. Never touches username,
        oidc_provider, or oidc_subject."""
        updates: dict[str, Any] = {}
        if user_data.get("email") and user.email != user_data["email"]:
            updates["email"] = user_data["email"]
        if user_data.get("display_name") and user.display_name != user_data["display_name"]:
            updates["display_name"] = user_data["display_name"]
        if not updates:
            return user
        return users.update_user(user.id, **updates) or user
```

### 1.5 Router

`backend/routers/oidc.py::handle_callback` — add one clause to the existing `except` chain, before
`except OIDCError`:

```python
    except OIDCIdentityConflictError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
```

### 1.6 Admin linking (small, optional follow-up)

Because auto-linking is gone, an admin needs a way to attach an IdP identity to a pre-existing
local account. Smallest version: extend `UserUpdate` with `oidc_provider` and `oidc_subject`
(both optional, `users:write`), shown as two fields in the user dialog. Not required for release;
new OIDC users still self-provision as inactive and get approved by an admin as today.

Scope note (R5): `UserAdminResponse` in `backend/models/rbac.py` exposes neither `email` nor
`oidc_provider`/`oidc_subject`, so an admin cannot see the current binding before setting one.
Doing 1.6 therefore means: add those three fields to `UserAdminResponse` and to the user list
table, then add the two editable fields to `UserUpdate` and the dialog. Budget half a day, not
one field.

### 1.7 Tests (write first)

`tests/unit/test_oidc_service.py`:

- `test_existing_active_user_is_returned` → rename to
  `test_existing_user_matched_by_provider_and_subject_is_returned`; the fixture row must carry
  `oidc_provider` and `oidc_subject`.
- `test_username_collision_with_local_account_raises_conflict` — local user `admin`
  (`oidc_provider=None`), IdP claims `preferred_username=admin`, `sub=x` → raises
  `OIDCIdentityConflictError`, row unchanged.
- `test_username_collision_with_other_provider_raises_conflict`.
- `test_same_provider_different_subject_raises_conflict`.
- `test_profile_sync_never_changes_username_or_identity`.
- `test_missing_sub_claim_raises` (in `extract_user_data`).
- `test_new_user_is_created_with_subject`.

`tests/unit/test_oidc_router.py` (new): callback returns 403 on conflict and never sets a token.

### 1.8 Verification

1. `python -m pytest tests/unit/test_oidc_service.py tests/unit/test_oidc_router.py --no-cov`
2. Start the backend; confirm the log line "Schema sync: … 1 column(s) added, 1 index(es) created".
3. Manual: with a test IdP user whose `preferred_username` is `admin`, complete the login; expect
   HTTP 403 and the local admin row untouched (`SELECT oidc_provider, oidc_subject FROM users WHERE username='admin'`).

---

## 2. RBAC: put a grant policy into `RBACService`

### 2.1 Problem in one sentence

The only guard today is "system roles need an admin actor"; permission overrides, role removal,
non-system role grants, and system-role renames have no policy at all, so `users:write` is
effectively `admin`.

### 2.2 Policy (model D2-b)

| Rule | Statement |
|---|---|
| P1 | An actor may never change their own roles or overrides, delete or deactivate themselves. |
| P2 | An actor may grant (via override or via role) only permissions they currently hold. `admin` bypasses. |
| P3 | Any grant, override, or removal touching the protected resources `rbac.*`, `users`, `system.*` requires `admin`. |
| P4 | Any change to a user who currently holds `admin` requires `admin`. |
| P5 | System roles cannot be renamed, deleted, or have their `is_system` flag changed. |
| P6 | The last user holding `admin` cannot lose it (role removal, deactivation, deletion). |
| P7 | Internal callers (seed, lifespan) pass `actor_user_id=None` and bypass the policy, as today. |

### 2.3 Service

`backend/services/auth/rbac_service.py`.

Before (the only guard):

```python
    def _require_admin_actor(self, actor_user_id: int | None) -> None:
        if actor_user_id is None:
            return
        if not self.has_role(actor_user_id, "admin"):
            raise AccessDeniedError("Admin role required to modify system roles")
```

After — policy section added to the class (the old method stays for the system-role paths):

```python
ADMIN_ROLE_NAME = "admin"
# Permissions on these resources let a holder change who can do what; only
# admins may hand them out or take them away (policy P3).
PROTECTED_RESOURCES: tuple[str, ...] = ("rbac.", "users", "system.")


def _is_protected(permission: Permission) -> bool:
    return any(
        permission.resource == prefix.rstrip(".") or permission.resource.startswith(prefix)
        for prefix in PROTECTED_RESOURCES
    )


class RBACService:
    ...
    # ---- policy helpers ---------------------------------------------------

    def _is_admin(self, user_id: int | None) -> bool:
        return user_id is not None and self.has_role(user_id, ADMIN_ROLE_NAME)

    def _assert_not_self(self, actor_user_id: int | None, target_user_id: int) -> None:
        if actor_user_id is not None and actor_user_id == target_user_id:
            raise AccessDeniedError("You cannot change your own roles or permissions")  # P1

    def _assert_may_touch_target(self, actor_user_id: int | None, target_user_id: int) -> None:
        if actor_user_id is None or self._is_admin(actor_user_id):
            return
        if self._is_admin(target_user_id):
            raise AccessDeniedError("Admin role required to modify an administrator")  # P4

    def _assert_actor_holds(self, actor_user_id: int | None, permissions: list[Permission]) -> None:
        if actor_user_id is None or self._is_admin(actor_user_id):
            return
        for permission in permissions:
            if _is_protected(permission):
                raise AccessDeniedError(
                    f"Admin role required to grant {permission.resource}:{permission.action}"
                )  # P3
            if not self.has_permission(actor_user_id, permission.resource, permission.action):
                raise AccessDeniedError(
                    f"You cannot grant {permission.resource}:{permission.action} "
                    "because you do not hold it"
                )  # P2

    def _assert_not_last_admin(self, user_id: int) -> None:
        admin_role = self._repo.get_role_by_name(ADMIN_ROLE_NAME)
        if admin_role is None or not self.has_role(user_id, ADMIN_ROLE_NAME):
            return
        if len(self._repo.get_users_with_role(admin_role.id)) <= 1:
            raise AccessDeniedError("The last administrator cannot be removed")  # P6
```

Mutating methods, before → after:

```python
    # before
    def update_role(self, role_id: int, **kwargs: object):
        return self._repo.update_role(role_id, **kwargs)

    # after (P5)
    def update_role(self, role_id: int, *, name: str | None = None, description: str | None = None):
        role = self.get_role(role_id)
        if role is None:
            return None
        if role.is_system and name is not None and name != role.name:
            raise AccessDeniedError("System roles cannot be renamed")
        return self._repo.update_role(role_id, name=name, description=description)
```

```python
    # before
    def assign_permission_to_role(self, role_id, permission_id, granted=True, *, actor_user_id=None):
        role = self.get_role(role_id)
        if role is not None and role.is_system:
            self._require_admin_actor(actor_user_id)
        return self._repo.assign_permission_to_role(role_id, permission_id, granted)

    # after (P2/P3 also for non-system roles)
    def assign_permission_to_role(self, role_id, permission_id, granted=True, *, actor_user_id=None):
        role = self.get_role(role_id)
        if role is not None and role.is_system:
            self._require_admin_actor(actor_user_id)
        permission = self._repo.get_permission_by_id(permission_id)
        if permission is not None and granted:
            self._assert_actor_holds(actor_user_id, [permission])
        return self._repo.assign_permission_to_role(role_id, permission_id, granted)
```

```python
    # before
    def assign_role_to_user(self, user_id, role_id, *, actor_user_id=None):
        role = self.get_role(role_id)
        if role is not None and role.is_system:
            self._require_admin_actor(actor_user_id)
        return self._repo.assign_role_to_user(user_id, role_id)

    # after (P1, P2, P4)
    def assign_role_to_user(self, user_id, role_id, *, actor_user_id=None):
        self._assert_not_self(actor_user_id, user_id)
        self._assert_may_touch_target(actor_user_id, user_id)
        role = self.get_role(role_id)
        if role is not None and role.is_system:
            self._require_admin_actor(actor_user_id)
        elif role is not None:
            self._assert_actor_holds(actor_user_id, self._repo.get_role_permissions(role.id))
        return self._repo.assign_role_to_user(user_id, role_id)
```

```python
    # before
    def remove_role_from_user(self, user_id: int, role_id: int) -> bool:
        return self._repo.remove_role_from_user(user_id, role_id)

    # after (P1, P4, P6; system-role removal is admin-only)
    def remove_role_from_user(self, user_id: int, role_id: int, *, actor_user_id: int | None = None) -> bool:
        self._assert_not_self(actor_user_id, user_id)
        self._assert_may_touch_target(actor_user_id, user_id)
        role = self.get_role(role_id)
        if role is not None and role.is_system:
            self._require_admin_actor(actor_user_id)
            if role.name == ADMIN_ROLE_NAME:
                self._assert_not_last_admin(user_id)
        return self._repo.remove_role_from_user(user_id, role_id)
```

```python
    # before
    def assign_permission_to_user(self, user_id, permission_id, granted=True):
        return self._repo.assign_permission_to_user(user_id, permission_id, granted)

    def remove_permission_from_user(self, user_id, permission_id) -> bool:
        return self._repo.remove_permission_from_user(user_id, permission_id)

    # after (P1–P4; a deny-override on a protected permission is as dangerous as an allow)
    def assign_permission_to_user(self, user_id, permission_id, granted=True, *, actor_user_id=None):
        self._assert_not_self(actor_user_id, user_id)
        self._assert_may_touch_target(actor_user_id, user_id)
        permission = self._repo.get_permission_by_id(permission_id)
        if permission is not None:
            if granted:
                self._assert_actor_holds(actor_user_id, [permission])
            elif _is_protected(permission):
                self._require_admin_actor(actor_user_id)
        return self._repo.assign_permission_to_user(user_id, permission_id, granted)

    def remove_permission_from_user(self, user_id, permission_id, *, actor_user_id=None) -> bool:
        self._assert_not_self(actor_user_id, user_id)
        self._assert_may_touch_target(actor_user_id, user_id)
        return self._repo.remove_permission_from_user(user_id, permission_id)
```

### 2.4 Users service (P1, P4, P6 for delete / deactivate)

`backend/services/users/user_service.py` — `UserService` gets an `RBACService` and:

```python
    def delete_user(self, user_id: int, *, actor_user_id: int | None = None) -> bool:
        self._assert_can_remove(user_id, actor_user_id)
        return self._repo.delete_user(user_id)

    def set_active(self, user_id: int, is_active: bool, *, actor_user_id: int | None = None):
        if not is_active:
            self._assert_can_remove(user_id, actor_user_id)
        return self._repo.set_active(user_id, is_active)

    def _assert_can_remove(self, user_id: int, actor_user_id: int | None) -> None:
        if actor_user_id is not None and actor_user_id == user_id:
            raise AccessDeniedError("You cannot delete or deactivate your own account")
        self._rbac.may_touch_target(actor_user_id, user_id)   # P4, public name of _assert_may_touch_target
        self._rbac.assert_not_last_admin(user_id)             # P6, public name of _assert_not_last_admin
```

`update_user` (backs `PUT /users/{id}`) today builds one `updates` dict for username, password
and `is_active` together. Rather than splitting `is_active` out into a second call, keep the
single repository write and run every guard **before** it, so a request that renames and
deactivates in one call either fully passes or fully fails (R5):

```python
    def update_user(
        self,
        user_id: int,
        username: str | None = None,
        password: str | None = None,
        is_active: bool | None = None,
        *,
        actor_user_id: int | None = None,
    ) -> User | None:
        # Guards first, write once. Order: P1/P4 (may I touch this user at all),
        # then P6 (would this remove the last admin), then the password policy.
        self._rbac.may_touch_target(actor_user_id, user_id)
        if is_active is False:
            self._assert_can_remove(user_id, actor_user_id)
        target = self._repo.get_by_id(user_id)
        if password is not None:
            validate_password(password, username=username or (target.username if target else None))

        updates: dict[str, object] = {}
        if username is not None:
            updates["username"] = username
        if password is not None:
            updates["password_hash"] = password_hash.hash(password)
            updates["must_change_password"] = True   # admin-set password (§4.4)
        if is_active is not None:
            updates["is_active"] = is_active
        return self._repo.update_user(user_id, **updates)
```

`may_touch_target` and `assert_not_last_admin` are the public names of the two RBAC helpers
above (`_assert_may_touch_target`, `_assert_not_last_admin`); make them public in §2.3 rather
than calling private methods across services.

Repository note (R5): `UserRepository.update_user` takes `**kwargs` and `setattr`s any existing
model attribute (analysis §4.4, out of scope here). This plan adds new call sites through that
same method (`must_change_password` in §4, `oidc_subject` in §1). Every new call site passes
explicit keyword arguments built in the service, never a request body dict, so the pattern is
extended but not exposed further.

### 2.5 Routers

Every mutating endpoint passes the actor. `backend/routers/rbac/user_access.py`, before:

```python
async def remove_user_role(user_id: int, role_id: int, service: RBACService = Depends(_service)) -> None:
    removed = service.remove_role_from_user(user_id, role_id)
```

after:

```python
async def remove_user_role(
    user_id: int,
    role_id: int,
    service: RBACService = Depends(_service),
    current_user: User = Depends(get_current_user),
) -> None:
    try:
        removed = service.remove_role_from_user(user_id, role_id, actor_user_id=current_user.id)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
```

Same shape for `set_user_permission_override`, `remove_user_permission_override`,
`routers/rbac/roles.py::update_role`, and `routers/users.py::delete_user`, `set_user_active`,
`update_user`. `AccessDeniedError` is a `DomainError`, so the global handler in `main.py` already
maps it to its status code; the explicit `try/except` is only needed where the router wants a
specific message.

### 2.6 Frontend impact

None required. Existing screens will receive 403s with a readable `detail`; the permissions
canvas already shows API errors as toasts. Optional: hide the "remove role" button on the
current user's own row.

### 2.7 Tests (write first)

`tests/unit/test_rbac_elevation.py` — add:

- `test_users_write_holder_cannot_override_protected_permission_for_self`
- `test_users_write_holder_cannot_override_permission_they_do_not_hold`
- `test_users_write_holder_cannot_touch_admin_user`
- `test_non_admin_cannot_remove_system_role_from_user`
- `test_last_admin_cannot_lose_admin_role`
- `test_non_admin_cannot_add_unheld_permission_to_custom_role`
- `test_non_admin_cannot_assign_custom_role_containing_unheld_permission`
- `test_system_role_cannot_be_renamed`
- `test_actor_none_bypasses_policy` (seed/lifespan path keeps working)
- `test_admin_can_do_all_of_the_above`

`tests/unit/test_rbac_roles_router.py` and a new `test_rbac_user_access_router.py`: each
mutating endpoint returns 403 for a non-admin acting on themselves and 204 for an admin.

`tests/unit/test_users_router.py` (new): self-delete → 403, delete last admin → 403.

### 2.8 Verification

1. `python -m pytest tests/unit -k "rbac or users" --no-cov`
2. Manual: create role `ops` with `users:write`, create user `bob` with `ops`; as `bob`, try
   `POST /api/rbac/users/<bob>/permissions {permission_id: <rbac.roles:write>, granted: true}` →
   403; `DELETE /api/rbac/users/<admin>/roles/<admin role>` → 403;
   `PUT /api/rbac/roles/<admin role> {name: "x"}` → 403.

---

## 3. Docker: non-root processes and no insecure defaults

### 3.1 Problem in one sentence

All three images run every process as root, and `docker/docker-compose.yml` hard-codes
`ENV: development`, the default `SECRET_KEY`, `admin/admin`, `DOCS_ENABLED: "true"`, an empty
`CREDENTIAL_ENCRYPTION_KEY`, and `postgres`/`changeme` passwords, so the production guards never run.

### 3.2 Images (model D3-a: root entrypoint that drops privileges)

`docker/Dockerfile.basic` and the `runtime` stage of `docker/Dockerfile.all-in-one` — before:

```dockerfile
RUN mkdir -p /app/data /var/log/supervisor

COPY docker/supervisord-web.conf /etc/supervisor/conf.d/supervisord.conf
COPY docker/start.sh /app/start.sh
RUN chmod +x /app/start.sh

EXPOSE 3000 8000

CMD ["/app/start.sh"]
```

after:

```dockerfile
# Unprivileged runtime account. start.sh runs as root only long enough to
# install operator CA certs and fix bind-mount ownership, then drops to it.
RUN groupadd --system manus \
 && useradd --system --gid manus --home-dir /app --shell /usr/sbin/nologin manus \
 && mkdir -p /app/data /app/config/certs /var/log/supervisor /run/supervisor \
 && chown -R manus:manus /app /var/log/supervisor /run/supervisor

COPY --chown=manus:manus docker/supervisord-web.conf /etc/supervisor/conf.d/supervisord.conf
COPY docker/start.sh /app/start.sh
RUN chmod 755 /app/start.sh

EXPOSE 3000 8000

# No USER here on purpose: the entrypoint drops privileges (see start.sh).
CMD ["/app/start.sh"]
```

`docker/Dockerfile.worker` — before:

```dockerfile
COPY backend/ .

ENV PYTHONPATH=/app/backend
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "hatchet.worker"]
```

after:

```dockerfile
COPY backend/ .

RUN groupadd --system manus \
 && useradd --system --gid manus --home-dir /app --shell /usr/sbin/nologin manus \
 && mkdir -p /app/data /app/config/certs \
 && chown -R manus:manus /app

ENV PYTHONPATH=/app/backend
ENV PYTHONUNBUFFERED=1

COPY docker/entrypoint-worker.sh /app/entrypoint-worker.sh
RUN chmod 755 /app/entrypoint-worker.sh

CMD ["/app/entrypoint-worker.sh"]
```

If you choose D3-b instead: add `USER manus` after the `chown` lines, delete the entrypoint
scripts, and remove `INSTALL_CERTIFICATE_FILES` from compose.

### 3.3 Entrypoints

`docker/start.sh` — before:

```bash
mkdir -p /app/data/settings
mkdir -p /app/data/git
mkdir -p /app/data/cache
mkdir -p /app/config/certs
mkdir -p /var/log/supervisor

chown -R root:root /app/data
chmod -R 755 /app/data

SUPERVISORD_CONF="${SUPERVISORD_CONF:-/etc/supervisor/conf.d/supervisord.conf}"
exec /usr/bin/supervisord -c "${SUPERVISORD_CONF}"
```

after:

```bash
#!/bin/bash
set -euo pipefail

mkdir -p /app/data/settings /app/data/git /app/data/cache /app/data/logs \
         /app/config/certs /var/log/supervisor /run/supervisor

if [ "$(id -u)" = "0" ]; then
  # Root-only work: operator CA certs and bind-mount ownership.
  if [ "${INSTALL_CERTIFICATE_FILES:-false}" = "true" ] && ls /app/config/certs/*.crt >/dev/null 2>&1; then
    cp /app/config/certs/*.crt /usr/local/share/ca-certificates/ && update-ca-certificates
  fi
  chown -R manus:manus /app/data /var/log/supervisor /run/supervisor
  # setpriv ships with util-linux in python:*-slim; no extra package needed.
  exec setpriv --reuid=manus --regid=manus --init-groups "$0" "$@"
fi

SUPERVISORD_CONF="${SUPERVISORD_CONF:-/etc/supervisor/conf.d/supervisord.conf}"
exec supervisord -c "${SUPERVISORD_CONF}"
```

`docker/entrypoint-worker.sh` (new): same root block, then
`exec python -m "${WORKER_MODULE:-hatchet.worker}"`. The background worker service sets
`WORKER_MODULE=hatchet.dynamic_worker`.

`backend/core/cert_installer.py` stays as is; running as `manus` it now logs "Permission denied"
and continues, which is the documented no-op behaviour. Once the entrypoint handles certs, set
`INSTALL_CERTIFICATE_FILES` only on the container (entrypoint) and not on the app processes, or
leave it and accept the one log line.

### 3.4 supervisord

`docker/supervisord-web.conf`, `supervisord.conf`, `supervisord-worker.conf`,
`supervisord-background-worker.conf` — before:

```ini
[supervisord]
nodaemon=true
user=root
logfile=/var/log/supervisor/supervisord.log
pidfile=/var/run/supervisord.pid
```

after:

```ini
[supervisord]
nodaemon=true
logfile=/var/log/supervisor/supervisord.log
pidfile=/run/supervisor/supervisord.pid
```

(`user=` removed: supervisord already runs as `manus`; `/var/run` is not writable by `manus`.)

### 3.5 Compose

`docker/docker-compose.yml` — before:

```yaml
x-manus-app-env: &manus-app-env
  ENV: development
  SECRET_KEY: change-in-production-use-at-least-32-characters
  ACCESS_TOKEN_EXPIRE_MINUTES: 60
  DOCS_ENABLED: "true"
  INITIAL_USERNAME: admin
  INITIAL_PASSWORD: admin
  CREDENTIAL_ENCRYPTION_KEY: ""
  ...
  DATABASE_PASSWORD: postgres
  MANUS_REDIS_PASSWORD: changeme
  HATCHET_CLIENT_TOKEN: "get-from-your-hatchet-dashboard"
```

after:

```yaml
# Secrets come from docker/.env (gitignored). Copy docker/.env.example and fill it in.
# `${VAR:?msg}` makes `docker compose up` fail with `msg` when VAR is unset or empty.
x-manus-app-env: &manus-app-env
  ENV: ${ENV:-production}
  SECRET_KEY: ${SECRET_KEY:?SECRET_KEY is required — generate with `openssl rand -hex 32`}
  ACCESS_TOKEN_EXPIRE_MINUTES: 60
  DOCS_ENABLED: ${DOCS_ENABLED:-false}
  INITIAL_USERNAME: ${INITIAL_USERNAME:-admin}
  INITIAL_PASSWORD: ${INITIAL_PASSWORD:?INITIAL_PASSWORD is required (12+ characters)}
  CREDENTIAL_ENCRYPTION_KEY: ${CREDENTIAL_ENCRYPTION_KEY:?CREDENTIAL_ENCRYPTION_KEY is required and must differ from SECRET_KEY}
  ...
  DATABASE_PASSWORD: ${DATABASE_PASSWORD:?DATABASE_PASSWORD is required}
  MANUS_REDIS_PASSWORD: ${MANUS_REDIS_PASSWORD:?MANUS_REDIS_PASSWORD is required}
  HATCHET_CLIENT_TOKEN: ${HATCHET_CLIENT_TOKEN:?HATCHET_CLIENT_TOKEN is required (Hatchet dashboard → API Tokens)}
```

and the infrastructure services use the same variables:

```yaml
  manus-postgres:
    environment:
      POSTGRES_PASSWORD: ${DATABASE_PASSWORD:?}
  manus-redis:
    command: ["redis-server", "--appendonly", "yes", "--requirepass", "${MANUS_REDIS_PASSWORD:?}"]
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${MANUS_REDIS_PASSWORD:?}", "ping"]
```

**`docker/.env.example` (R1: repurpose, do not create).** The file already exists as a stale,
filled-in copy of `backend/.env.example`. Today it is effectively dead: `docker-compose.yml`
contains no `${...}` substitution at all, so a `docker/.env` is never read, yet
`start-docker.sh` copies the example to `.env` and `docker/README.md` §"Environment variables"
tells operators to do the same. The plan makes that existing copy-to-`.env` workflow real:

1. Rewrite `docker/.env.example` in place: keep one comment line per variable, set every
   secret to an **empty** value (`SECRET_KEY=`, `INITIAL_PASSWORD=`,
   `CREDENTIAL_ENCRYPTION_KEY=`, `DATABASE_PASSWORD=`, `MANUS_REDIS_PASSWORD=`,
   `HATCHET_CLIENT_TOKEN=`), keep only the non-secret knobs that compose actually
   substitutes (`ENV`, `DOCS_ENABLED`, `INITIAL_USERNAME`, `HATCHET_CLIENT_HOST_PORT`,
   `HATCHET_CLIENT_TLS_STRATEGY`, `INSTALL_CERTIFICATE_FILES`, proxy vars). Drop everything
   that is not referenced by `docker-compose.yml`; the backend example stays the reference for
   non-Docker runs.
2. `docker/docker-compose.yml` header: replace "Edit values here — not via docker/.env" with
   "Secrets come from docker/.env (copy .env.example); non-secret defaults live in
   x-manus-app-env".
3. `docker/start-docker.sh`: remove the `cp .env.example .env` block. Replace it with: if
   `.env` is missing, print `cp .env.example .env` and the list of required variables, then
   exit 1. Auto-copying an all-empty template would only make `docker compose up` fail on the
   first `:?` guard with a less helpful message.
4. `.gitignore`: already covered. Line 154 is a bare `.env` pattern, which matches
   `docker/.env` in any directory. No change.

New file:

- `docker/docker-compose.dev.yml` — the old development values as an override:

  ```yaml
  x-dev-env: &dev-env
    ENV: development
    DOCS_ENABLED: "true"
  services:
    manus-web:
      environment: { <<: *dev-env }
    manus-worker:
      environment: { <<: *dev-env }
    manus-background-worker:
      environment: { <<: *dev-env }
  ```

  used as `docker compose -f docker-compose.yml -f docker-compose.dev.yml up`. Secrets still
  come from `.env` even in development, so nobody ships the defaults by accident.

### 3.6 Backend guard hardening (cheap, do at the same time)

`backend/core/production_guards.py` — two additions (the second is R2: the seeded admin is
created via `UserRepository.create_user` directly, never through `UserCreate` or
`validate_password`, so without this an operator setting `INITIAL_PASSWORD=xyz1` gets a
four-character admin password in production while every other path enforces 12). Before:

```python
    if secret_key == DEFAULT_SECRET_KEY:
        raise RuntimeError("SECRET_KEY must be configured outside development")
    if initial_password == DEFAULT_INITIAL_PASSWORD:
        raise RuntimeError("INITIAL_PASSWORD must be configured outside development")
```

after:

```python
    if secret_key == DEFAULT_SECRET_KEY:
        raise RuntimeError("SECRET_KEY must be configured outside development")
    if len(secret_key) < MIN_SECRET_KEY_LENGTH:
        raise RuntimeError("SECRET_KEY must be at least 32 characters outside development")
    if initial_password == DEFAULT_INITIAL_PASSWORD:
        raise RuntimeError("INITIAL_PASSWORD must be configured outside development")
    if len(initial_password) < PASSWORD_MIN_LENGTH:
        raise RuntimeError("INITIAL_PASSWORD must be at least 12 characters outside development")
```

with `MIN_SECRET_KEY_LENGTH = 32` next to the other module constants and `PASSWORD_MIN_LENGTH`
imported from `services.auth.password_policy` (§4.2). The guard runs only outside development,
so `admin/admin` in a dev environment keeps working; there the forced change on first login
(§4.4, §4.6) is the safety net. Tests in `tests/unit/test_production_guards.py`: 31-character
`SECRET_KEY` raises; 11-character `INITIAL_PASSWORD` raises; both pass in `development`.

### 3.7 Docs

Update `docker/README.md`, `docker/DOCKER.md`, `INSTALL.md`: the "Backend won't start
(SECRET_KEY / INITIAL_PASSWORD)" section becomes the normal path; add the `.env.example` step and
the `-f docker-compose.dev.yml` recipe. In `docker/README.md` specifically: the file table row
"`.env.example` — Optional template (prefer editing `x-manus-app-env` in compose)" becomes
"Required secrets template; copy to `.env`", and the "Environment variables" block loses its
`postgres`/`changeme` sample values.

### 3.8 Verification

1. `docker compose config` fails with the `:?` message when `docker/.env` is absent.
2. `docker compose up -d` with a filled `.env`; `docker exec manus-web ps -o user,cmd` shows every
   `python`/`node`/`supervisord` process as `manus`.
3. `docker exec manus-web id -u` → non-zero; `curl -s localhost:8000/docs` → 404.
4. `docker/test-docker-deployment.sh` and `validate-all-in-one.sh` still pass.
5. With `INSTALL_CERTIFICATE_FILES=true` and a `.crt` in `config/certs/`, the container log shows
   `update-ca-certificates` output before supervisord starts, and `openssl verify` inside the
   container accepts the private CA.

---

## 4. Password policy, self-service change, forced change of the bootstrap password

### 4.1 Problem in one sentence

`UserCreate`/`UserUpdate` accept a one-character password, only `users:write` can set passwords,
and nothing forces the seeded `admin` to replace `INITIAL_PASSWORD`.

### 4.2 Policy module (new)

`backend/services/auth/password_policy.py`:

```python
"""Password acceptance rules (NIST SP 800-63B style: length, not composition)."""

from __future__ import annotations

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128
_DENYLIST = frozenset({"password", "passw0rd", "admin", "changeme", "letmein", "welcome"})


class PasswordPolicyError(ValueError):
    """Raised with a user-facing message when a password is not acceptable."""


def validate_password(password: str, *, username: str | None = None) -> None:
    if len(password) < PASSWORD_MIN_LENGTH:
        raise PasswordPolicyError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise PasswordPolicyError(f"Password must be at most {PASSWORD_MAX_LENGTH} characters")
    lowered = password.lower()
    if lowered in _DENYLIST:
        raise PasswordPolicyError("This password is too common")
    if username and lowered == username.lower():
        raise PasswordPolicyError("Password must not equal the username")
```

### 4.3 Request models

`backend/models/rbac.py` — before:

```python
class UserCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=128)
    is_active: bool = True


class UserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=1, max_length=128)
    is_active: bool | None = None
```

after:

```python
from services.auth.password_policy import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    is_active: bool = True


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(
        default=None, min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH
    )
    is_active: bool | None = None
```

`backend/models/auth.py` — add:

```python
class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(..., min_length=1, max_length=PASSWORD_MAX_LENGTH)
    new_password: str = Field(..., min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
```

and `must_change_password: bool = False` on `UserResponse`. (The Pydantic length checks give a
fast 422; the denylist/username rule runs in the service so it can see the username.)

### 4.4 Model and seed

`backend/core/models/users.py` — add:

```python
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
```

`backend/services/auth/auth_service.py::ensure_initial_admin` — before:

```python
            return self.users.create_user(
                username=settings.initial_username,
                password_hash=password_hash.hash(settings.initial_password),
                is_active=True,
            )
```

after:

```python
            return self.users.create_user(
                username=settings.initial_username,
                password_hash=password_hash.hash(settings.initial_password),
                is_active=True,
                must_change_password=True,   # bootstrap credential is never a long-term one
            )
```

This path deliberately does **not** call `validate_password`: it must keep working with
`admin/admin` in development, and outside development the startup guard in §3.6 (R2) already
rejects a short `INITIAL_PASSWORD` before the seed runs. Do not add a second check here.

New service method:

```python
    def change_password(self, user: User, current_password: str, new_password: str) -> User:
        if not password_hash.verify(current_password, user.password_hash):
            raise AuthenticationError("Current password is incorrect")
        validate_password(new_password, username=user.username)   # PasswordPolicyError → 400
        updated = self.users.update_user(
            user.id,
            password_hash=password_hash.hash(new_password),
            must_change_password=False,
        )
        return updated or user
```

`UserService.create_user` / `update_user` call `validate_password(password, username=...)`
before hashing, and admin-set passwords set `must_change_password=True` so the user replaces
what the admin typed.

### 4.5 Endpoint

`backend/routers/auth.py` — add:

```python
@router.post("/change-password", response_model=UserResponse)
async def change_password(
    body: PasswordChangeRequest,
    current_user: User = Depends(get_current_user_allow_password_change),
    db: Session = Depends(get_db),
) -> UserResponse:
    try:
        user = AuthService(db).change_password(
            current_user, body.current_password, body.new_password
        )
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _build_user_response(user, db)
```

Rate-limit it with the existing `LoginRateLimiter` keyed by `user_id` (5 attempts / minute) so
the `current_password` check cannot be brute-forced.

### 4.6 Enforcement (D5: backend)

`backend/core/auth.py` — before:

```python
def get_current_user(token_payload=Depends(verify_token), db=Depends(get_db)) -> User:
    ...
    if user is None or not user.is_active:
        raise HTTPException(401, ...)
    return user
```

after:

```python
PASSWORD_CHANGE_REQUIRED_DETAIL = {"code": "password_change_required",
                                   "message": "You must change your password before continuing"}


def _load_active_user(token_payload: dict[str, Any], db: Session) -> User:
    user_id = _require_user_id(token_payload)
    user = UserRepository(db).get_by_id(user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid authentication token",
                            headers=AUTHENTICATE_HEADER)
    return user


def get_current_user_allow_password_change(
    token_payload: dict[str, Any] = Depends(verify_token),
    db: Session = Depends(get_db),
) -> User:
    """For /auth/me, /auth/change-password, /auth/refresh only."""
    return _load_active_user(token_payload, db)


def get_current_user(
    user: User = Depends(get_current_user_allow_password_change),
) -> User:
    if user.must_change_password:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=PASSWORD_CHANGE_REQUIRED_DETAIL)
    return user
```

and `_require_active_user_id` (used by every `require_*`) applies the same
`must_change_password` check, so router-level permission dependencies also block. This also
collapses the duplicated user lookup noted in the analysis (§6.4).

`/auth/me` switches to `get_current_user_allow_password_change` so the frontend can read
`must_change_password` and redirect.

### 4.7 Frontend (one feature slice, about one day)

This is a normal feature slice, not a tweak (R3): the shared `useApi` hook is used by every
query and mutation, and a hook cannot render a dialog. The design reuses the user object already
held in `useAuthStore` as the single signal, so no new store or flag is introduced.

**a) Types and the three response parsers (R4).** `frontend/src/lib/auth.ts::AuthUser` gains
`must_change_password: boolean`. Three near-identical parsers validate and copy the backend
user shape field by field; all three must be updated or the flag is dropped on that path:

| File | Function | Used by |
|---|---|---|
| `frontend/src/app/api/auth/login/route.ts` | `parseUserResponse` | login |
| `frontend/src/app/api/auth/refresh/route.ts` | `parseSessionResponse` | session renewal (`useSessionManager`) |
| `frontend/src/app/api/auth/me/route.ts` | `parseUserResponse` | `useAuthStore.loadCurrentUser()` on every page load |

In each: accept `must_change_password` as `boolean`, default `false` when absent (older backend),
and copy it into the returned object. Missing the `me` route is the bug the review caught: a user
who closes the tab and reopens the app would lose the flag client-side until the next 403.

**b) `useApi` 403 handling.** `frontend/src/hooks/use-api.ts` — before:

```ts
      if (response.status === 403) {
        throw new Error("Permission denied");
      }
```

after:

```ts
      if (response.status === 403) {
        const detail = await readErrorDetail(response);   // { code?, message? } | string | null
        if (typeof detail === "object" && detail?.code === PASSWORD_CHANGE_REQUIRED_CODE) {
          markPasswordChangeRequired();
          throw new Error(detail.message ?? "You must change your password before continuing");
        }
        throw new Error("Permission denied");
      }
```

where `readErrorDetail` is the existing body-parsing block from the `!response.ok` branch
extracted into a small helper (it already understands both the `string` and `{ message }`
shapes; extend the type with `code?: string`), `PASSWORD_CHANGE_REQUIRED_CODE =
"password_change_required"` lives in `frontend/src/lib/auth.ts`, and
`markPasswordChangeRequired` is a new `useAuthStore` action:

```ts
  markPasswordChangeRequired: () =>
    set((state) =>
      state.user ? { user: { ...state.user, must_change_password: true } } : {}
    ),
```

Called as `useAuthStore.getState().markPasswordChangeRequired()` inside the hook so `useApi`
does not subscribe to the store and re-render its callers.

**c) The dialog.** New `components/features/auth/change-password-dialog.tsx` (Shadcn `Dialog`,
react-hook-form + zod: `current_password` min 1, `new_password` min 12 max 128, `confirm` must
match). It posts to `auth/change-password` through a `useChangePasswordMutation` hook in
`hooks/queries/use-auth-mutations.ts`; on success it calls `useAuthStore.setUser(response)` so
`must_change_password` flips to `false` from the server's own response, then invalidates all
queries so the blocked calls re-run.

Two ways to open it:

- **Forced**: `components/layout/dashboard-shell.tsx` reads `user` from `useAuthStore` and
  renders `<ChangePasswordDialog open={user?.must_change_password === true} forced />`.
  `forced` disables close-on-outside-click, the close button and Escape
  (`onOpenChange` ignored while forced), and shows the explanatory text.
- **Voluntary**: a "Change password" item in the existing profile/user menu in `app-sidebar.tsx`
  opens the same component with `forced={false}`.

Because the dialog lives in `DashboardShell`, it appears on whichever page the user is on when
the 403 arrives, and on page reload via the `me` route parser (a). It talks to the backend only
through `/auth/change-password` and `/auth/me`, the two endpoints that accept a user in the
must-change state (§4.6).

**d) Admin user dialog.** `settings/permissions/dialogs/user-dialog.tsx`: password field
`min(12)` / `max(128)` and helper text "The user must change this password at first login".

**e) Frontend tests.** `use-api` unit test: a 403 with `{detail: {code: "password_change_required"}}`
flips the store flag and rejects; a 403 with a plain string detail rejects with "Permission
denied" and leaves the store alone. Parser tests for the three routes: flag copied through,
absent flag defaults to `false`.

### 4.8 Tests (write first)

- `tests/unit/test_password_policy.py`: length bounds, denylist, equals-username, happy path.
- `tests/unit/test_auth_change_password.py`: wrong current password → 400; policy violation →
  400; success clears `must_change_password` and the new password logs in; the old one does not.
- `tests/unit/test_require_permission_inactive_user.py` — extend: user with
  `must_change_password=True` gets 403 with `code=password_change_required` on a permission-gated
  route, 200 on `/auth/me` and `/auth/change-password`.
- `tests/unit/test_users_router.py`: `POST /users` with an 8-character password → 422.
- `tests/unit/test_auth_service.py`: `ensure_initial_admin` sets `must_change_password=True` only
  on creation.

### 4.9 Verification

1. `python -m pytest tests/unit -k "password or auth" --no-cov`
2. Fresh database, log in as the seeded admin: every `/api/proxy/*` call returns 403
   `password_change_required`, the dialog opens, a 12+ character password is accepted, subsequent
   calls succeed, `INITIAL_PASSWORD` no longer logs in.

---

## 5. Order of work and effort

| Step | Depends on | Effort |
|---|---|---|
| 3 Docker (images, entrypoints, compose, repurposed `.env.example`, `start-docker.sh`, guards) | D3 | 0.5 day |
| 4 Password policy + change endpoint + enforcement | D4, D5 | 0.5 day |
| 4.7 Frontend slice (parsers, `useApi`, store action, dialog, tests) | 4 | 1 day |
| 1 OIDC identity binding | D1 | 0.5 day |
| 2 RBAC policy (incl. `update_user` restructuring in §2.4) | D2 | 1 day (mostly tests) |
| Docs: CLAUDE.md auth section, SECURITY-NOTES, docker docs | all | 0.25 day |
| 1.6 Admin OIDC linking (optional, after release) | 1 | 0.5 day |

Docker goes first because it is independent and removes the "default secret in production"
exposure immediately. Steps 1, 2, 4 each touch `core/auth.py` or `User`; do 4 before 1 and 2 so
the `get_current_user` refactor lands once.

Out of scope here but adjacent: token invalidation on password change (S5). Step 4 creates the
natural hook (`change_password`); adding a `token_version` column and claim there is a
half-day follow-up.

## 6. Definition of done

- All tests in §1.7, §2.7, §4.8 exist and pass; coverage ratchet still ≥ 81 %.
- `ruff check` clean on touched files; the four `scripts/check_*.py` guards pass.
- `docker compose up` refuses to start without `docker/.env`; processes run as `manus`;
  `docker/.env.example` contains no secret values; `start-docker.sh` no longer auto-creates `.env`.
- Outside development, a `SECRET_KEY` under 32 or an `INITIAL_PASSWORD` under 12 characters
  fails at startup (§3.6).
- All three auth response parsers copy `must_change_password`; reloading the page while the
  flag is set reopens the forced dialog without waiting for a 403.
- `doc/analysis/FABLE_BACKEND_20260902.md` §5.3 rows S1, S2, S3, S4, S6 updated to "fixed" with
  the commit hash.
- CLAUDE.md "Authentication & Authorization" section documents: identity binding by
  `(oidc_provider, oidc_subject)`, the RBAC grant policy P1–P7, the password policy constants,
  and `must_change_password` enforcement.
