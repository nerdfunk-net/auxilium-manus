# Authentication & Authorization

## JWT Token Structure
```python
{
  "sub": "username",
  "user_id": 123,
  "iat": 1234567890,      # mint time (Unix seconds)
  "sid_iat": 1234567890,  # REQUIRED; original login time; carried UNCHANGED through every refresh
  "jti": "…",             # random per-token id (minted, not yet consumed)
  "tv": 0,                # REQUIRED; user.token_version at mint time
  "exp": 1234567890,      # clamped so it never outlives sid_iat + SESSION_MAX_AGE_HOURS
}
```
Permissions are **not** embedded in the JWT. Authorization is evaluated per-request
against the database via `RBACService.has_permission(user_id, resource, action)` — there
is no caching and no JWT permission claim to keep in sync.

**Logout is global.** `POST /auth/logout` bumps `token_version`, so it ends *every* session of that user on every device. The one exception is the browser idle timeout: it calls `/api/auth/logout?scope=local`, which only clears this browser's cookie (all tabs share one activity clock in `localStorage`). That is the deliberate, conservative choice: per-session logout would need a Redis denylist lookup on every request (`jti` is minted so one can be added later).

**Revocation (`token_version`).** `users.token_version` is an int column embedded in every
access token as `tv`. Bumping it invalidates every outstanding token for that user. It is
bumped by: `AuthService.bump_token_version` (`POST /auth/logout`), `AuthService.change_password`
(self-service change — folded into the same write), and `UserService.update_user` /
`set_active` on an admin password change, username change, or deactivation.
`core/auth.py::_load_active_user` rejects (401) a token whose `tv` is missing, not an int
(`bool` excluded) or differs from the row's `token_version`, and one whose `sid_iat` is missing or
not a number (T3: both claims are mandatory, fail closed). `AuthService.refresh_access_token` is
equally strict. Tokens minted before S5 are no longer accepted; the client is sent to login. Tests
that stub `verify_token` must use `tests/unit/_auth_helpers.py::token_payload` (guarded by
`test_no_minimal_token_stubs.py`).

**Absolute session lifetime (`SESSION_MAX_AGE_HOURS`, default 12, floor 1).** `REFRESH_TOKEN_MAX_AGE_HOURS` defaults to the same value and may not exceed it (T4). Measured from
`sid_iat`, which `create_access_token` preserves across refreshes. `_load_active_user` and
`refresh_access_token` both reject a session older than this regardless of per-token `exp`.
A successful `POST /auth/change-password` returns a fresh `SessionResponse` (new token,
`sid_iat = now`); `app/api/auth/change-password/route.ts` re-sets the auth cookie so the
forced-change flow does not bounce the user back to login.

**Login rate limiting (T1).** `POST /auth/login` uses two independent *failure* budgets:
per client IP (20 failures/60s) and per username (100 failures/15min); a success clears only
the username bucket. Client IP comes from `core/client_ip.py::resolve_client_host` —
honoured only when the direct peer is in `TRUSTED_PROXY_IPS` (IPs or CIDRs).
The budgets are counted in Redis; when Redis is unreachable the login, refresh, OIDC-login and webhook
limiters count in-process instead (exact with one web process, per replica with several) and log an error.
`RATE_LIMIT_FAIL_CLOSED=true` refuses those requests instead, which blocks every login and token refresh
until Redis is back (access tokens last one hour); use it only behind several replicas.
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
| P3 | Any change touching `rbac.*`, `users`, `system.*`, `secret_manager.*`, or `sources.*:write` / `sources.*:delete`, or `git.repositories:write` / `git.repositories:delete`, or `workflows:release_ai` requires `admin`. |
| P4 | Any change to a user who currently holds `admin` requires `admin`. |
| P5 | System roles (`is_system=True`) cannot be renamed, deleted, or have `is_system` changed. |
| P6 | The last **active** user holding `admin` cannot lose it (role removal, deactivation, deletion). Deactivated admins do not count. |
| P7 | Internal callers (seed, lifespan) pass `actor_user_id=None` and bypass P1–P4. |
| P8 | Password reset or username change of another user requires target's permissions to be a subset of the actor's with no protected permission (else requires `admin`). |
| T2 | Nobody (admins included) may change their own password or username via `PUT /users/{id}`; self-service is `POST /auth/change-password`. |
| R3 | Reactivating a user follows P4 (only `admin` may reactivate an administrator). |
| R4 | Permissions seeded in `rbac_seed.DEFAULT_PERMISSIONS` cannot be deleted (409). |
| R5 | Deleting a role held by an administrator requires `admin` (P4). |

Every mutating `RBACService`/`UserService` method takes `actor_user_id: int | None`; routers
pass `current_user.id` and map `AccessDeniedError` → 403. See
`backend/services/auth/rbac_service.py` and `backend/services/users/user_service.py`.

## The `viewer` role

`viewer` (the default role of an approved SSO user) is a small, explicit set - workflows, runs,
Nautobot inventory, change requests, reports, templates, workflow-step catalog, and read access to
repository files (`VIEWER_PERMISSIONS` in `services/auth/rbac_seed.py`). No users,
roles, credentials, settings, sources or repository configuration. The seed re-asserts exactly this
set at every start, so operators who need more create a custom role. Role-level deny is not a
thing: a role grants only; allow and deny overrides exist per user. The encrypt/decrypt test routes
need `workflows:execute` to use a stored shared secret.

A page that uses a Nautobot source reads its id, URL and readiness from
`GET /sources/nautobot/configured-sources` (`sources.nautobot:read`, so viewers can use the inventory page and the
template editor), never from `GET /settings` (`settings:read`). The response has `source_id`, `url` and
`token_configured` only (a row without a URL is left out, as the settings parser always did); the settings form still edits the `sources.nautobot.*` rows, and a write there refreshes the
page-side query (`use-settings-mutations.ts`).

**Agent sources.** `sources.agent` (`read` / `write` / `delete`) follows the same rules: writes are admin-only
(P3), the seeded `viewer` role has no `read`, and `POST /sources/agent/test-connection` needs `write` and is
rate limited. The shared secret is a global `shared_secret` credential referenced by id; no response or query
carries it (`doc/AGENT_INTEGRATION.md`).

**Ask the Net config backups.** `list_config_backups` / `get_config_backup` / `search_config_backups` (all devices, `doc/AI_TOOL_CHAIN.md` §41) read a device's config from a
`device_configs` git repository. They need `git.files:read` (checked on every call, which the seeded `viewer` role
holds) and the user's content opt-in; no operator switch. The path comes from the repository's
`config_path_running` / `config_path_startup` template, which only an admin can set (P3), never from the model
(`doc/AI_TOOL_CHAIN.md` §30).

**Released workflows** (`workflows:release_ai`, protected by P3: only an admin grants it, no seeded role holds it).
A holder may release a non-private workflow they manage (creator or admin) for Ask the Net, with a description
and one designated result step; `PUT/DELETE /workflows/{id}/ai-release`. Any change to the saved canvas, edges,
groups or inputs, or making the workflow private, clears the release (notes, name and folder do not). The release is also
**hash-pinned** (`ai_release_stamp`, over the workflow, the release settings and every workflow it starts with
`start-workflow`): it counts only while the stamp still matches, so editing a child, a save that raced the release or a
confirmation made before a re-release cannot run a version nobody reviewed. A proposal is used once (random token id, recorded in Redis; if Redis is down the confirm is refused with 503, never started unrecorded). A release pins at most 50 workflows. The
assistant lists/describes only released workflows the user may see **and** may run (`workflows:execute`),
proposes a run (signed token, 10 minutes, bound to the user) and the user's click calls
`POST /ai/exec/workflow-run`, which starts it **as that user** through `RunService.trigger_ai_run`
(`trigger_type="ai_assistant"`, which the public run API cannot set) and re-checks the release. Secret and
credential-reference inputs are never settable by the model. **Devices and credentials** (`doc/AI_TOOL_CHAIN.md` §16.10):
the release names the text input a Get from User step reads (`ai_devices_input`); the assistant passes device *names*
or, only if the releaser switched on `ai_allow_free_ip`, a single IPv4 literal (`parse_ipv4_literal`, then
`validate_netmiko_preview_host` incl. the `allow_netmiko_arbitrary_hosts` switch outside development). The server
builds the `name,ip[,driver]` lines (`services/workflow/device_lines.py`, shared with `start-workflow`); the model never
writes that input. Credential run inputs the releaser marks (`ai_credential_inputs`) are filled by the **confirming
user** on the card with one of their own SSH credentials: `credentials` in `POST /ai/exec/workflow-run`, checked by the
reference resolver as that user (`RunService.trigger_ai_run`). `get_run_result` reads only the designated step,
through the `get_step_result` gates (content opt-in, redaction, truncation). `doc/AI_TOOL_CHAIN.md` §16.

**Ask the Net run tools** (`list_runs`, `get_run`, `get_step_result`, ...). The same tools as the runs-page assistant. They
need `workflow_runs:read` (checked on every call) and follow run visibility; the user's inventory and content opt-ins gate
device names and run content (`doc/AI_TOOL_CHAIN.md` §40).

**Ask the Net Nautobot tools** (`list_devices`, `list_ip_addresses`, `list_locations`, ...). They need `sources.nautobot:read`
(checked on every call, which the seeded `viewer` role holds) and a configured Nautobot source; the user's data opt-ins
gate the fields (inventory for devices, addresses for IPAM and addresses/serials). They run on the source's shared
Nautobot token, so what the token may read is what a user with the permission can ask for (`doc/AI_TOOL_CHAIN.md` §31).

**Ask the Net output parsing** (`parse_command_output`, the `parser` of a device command, `doc/AI_TOOL_CHAIN.md` §43). TextFSM needs nothing beyond the content opt-in. Genie also needs `sources.pyats:read` (checked on every call; the seeded `viewer` role does not hold it) and exactly one configured pyATS source; it sends the redacted output to that source's shim.

**Ask the Net Catalyst Center tools** (`find_catalyst_center_device`, `get_catalyst_center_device_details`). They need
`sources.catalyst_center:read` (checked on every call; the seeded `viewer` role does not hold it, so it has no such tools)
and report a missing source to the user. The user's inventory switch gates both tools, the addresses switch the
addresses and serials (and lookups by them), the content switch interface descriptions (`doc/AI_TOOL_CHAIN.md` §42).

**Ask the Net neighbour tools** (`propose_neighbor_discovery`, `get_discovery_result`, `get_modelled_neighbors`,
`get_neighbor_sources`, `doc/AI_TOOL_CHAIN.md` §45). Discovery is a proposal on the device-command path: it needs the
operator switch `AI_DEVICE_COMMANDS_ENABLED`, `netmiko:execute`, the content opt-in and the user's click; the commands
come from a reviewed catalogue, never from the model. `get_discovery_result` is a read of the user's own stored output
(content opt-in checked on every call); comparing it with Nautobot cabling (always for the device the output came from, never one the model
names) also needs `sources.nautobot:read` and the addresses switch. `get_modelled_neighbors` needs Batfish access and the addresses switch.

**Assistant glossary** (inventory terms and workflow step aliases). `ai_glossary_terms` is global
and its words steer the model, so every `/ai/glossary` route, for both kinds, needs the `admin` role (P3 style); the seeded `viewer` and other roles have no
access. The assistant reads entries through the `get_glossary` tool as the calling user.

## Run control, change requests, schedules

**Child runs.** A `start-workflow` step starts another workflow as the *triggering user of the
calling run* (`RunService.require_child_target`: the workflow must be visible to them and they need
`workflows:execute`; a run without a triggering user cannot start one). It cannot be used to run
something the user could not run by hand. The child's owner is therefore the same user, so cancelling
the calling run cancels the child (`parent_run_id`) under the same owner-only rule.

Only the person who started a run (`triggered_by_id`, else the workflow's creator) may cancel it,
approve its Wait & Run batches or delete it; an administrator may cancel or delete (never approve)
as a logged exception. Approving a change request runs only the deploy workflow staged with it, as the
approver, who therefore needs `change_requests:approve` **and** `workflows:execute` and access to
that workflow. A schedule fires as its creator and is re-validated at every fire (creator active,
holds `workflows:execute`, can see the workflow) or it is disabled; deactivating a user disables, and
deleting a user deletes, their schedules; only the creator (or an admin, logged) edits or deletes one.
Administrators may manage any workflow; deleting a user hands their workflows to the acting admin.

**No per-object owner check.** Templates, report definitions, global inventories and global
credentials have none: whoever holds the write or delete permission can change another user's item.
A template edit changes what other users' workflows deploy; `credentials:write` lets a holder replace
a global credential's secret or make it private, which breaks every workflow, source and repository
that uses it. **Deleting a credential that something still uses is refused** with `409` and
`{code: "credential_in_use", dependants: [{kind, id, name}]}` (git repositories, secret-manager
connections, templates, sources, the mail settings, the AI assistant proxy, workflow canvases; finder in
`services/credentials/usage.py`). `DELETE /credentials/{id}?force=true` deletes anyway; the delete
dialog offers that after showing the list. **Refresh tokens are not single-use** (a deliberate trade-off): a stolen token can be
refreshed in parallel with its owner until logout or the session cap; refresh is rate limited.

**Settings every session needs.** The idle-logout timeout and `switch_to_runs_on_start` are read from
`GET /general/client-settings`, which any signed-in user may call (no `general_settings:read`); it never includes the
export directory. The admin form keeps using `GET/PUT /general/settings`.

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

**Linking an existing local account.** Nothing links by username, so an admin binds an
existing user to an IdP identity deliberately, from the host:
`cd backend && python scripts/link_oidc_identity.py <username> <provider_id> <subject>`.
It refuses an identity already bound to another user and bumps `token_version`, which ends the
user's existing sessions. There is intentionally no API for this (T6).

**Auth-request hardening.** Authorization requests carry a `nonce` and PKCE
(`code_challenge`/`code_challenge_method=S256`). `routers/oidc.py` stores
`{redirect_uri, nonce, code_verifier}` as the Redis state value; the callback verifies
`code_verifier` and `nonce` (constant-time compare; missing/mismatch → `OIDCError`).
The callback body is `{code, state}`; the token exchange uses the redirect URI stored with the state
(a supplied `redirect_uri` is only an equality check). `client_secret` resolves from `OIDC_<PROVIDER_ID>_CLIENT_SECRET` (provider id upper-cased,
non-alnum → `_`) with the YAML `client_secret` as fallback; an empty secret raises before
the HTTP call.

## Password Policy and Forced Change

`backend/core/password_policy.py::validate_password` — 12–128 characters,
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
