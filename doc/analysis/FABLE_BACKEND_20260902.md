# Backend Analysis — 2026-09-02

**Update 2026-09-02:** The release-blocking findings (S1, S2, S3, S4, S6) were fixed per
`doc/plans/FABLE_BACKEND_ISSUES.md`. S5, S7, S12, S13 were then fixed per
`doc/plans/FABLE_BACKEND_S5_S7_S12_S13.md`. S8, S10, S11 were then fixed per
`doc/plans/FABLE_BACKEND_S8_S10_S11.md` — see the Status column in §5.3 for commit hashes.
S9 and S14–S16 remain open.

**Update 2026-09-03:** First-hardening-pass items 7 and 9 were done per
`doc/plans/FABLE_REST.md`: §4.2 sync-only route handlers are now plain `def`
(threadpool), DNS resolution in the async external-API clients is offloaded via
`core.safe_urls.validate_outbound_http_url_async`, the Fernet-key cache (already
shipped in S12) gained a regression test, and `.github/workflows/backend-ci.yml`
runs ruff (with `S`/`ASYNC`), pyright, pip-audit, the four guard scripts, and the
test suite. `bandit` is covered by ruff's `S` ruleset rather than a standalone tool.

Reviewer: Claude Fable 5.1
Scope: `backend/` (FastAPI app, Hatchet workers, workflow steps). Frontend touched only where it
is part of the auth chain (Next.js proxy and cookie handling).
Goal stated by the owner: publish the app; it must be production ready with no obvious
security problems.

## 0. Verdict in one paragraph

The backend is in good shape structurally. The Model → Repository → Service → Router layering is
real, not aspirational: all four regression guards pass, ruff reports only 3 findings across
495 files, there is no f-string logging, no raw SQL outside the allow-list, no repository import in
any router, and every router-facing 5xx is sanitized. Auth fundamentals are sound (Argon2 via
pwdlib, constant-time dummy hash on unknown users, HS256 with `algorithms=[...]` pinned, per-request
DB-backed RBAC, deactivation enforced on every permission check, HTTP-only cookie via the Next.js
proxy, production guards that refuse default secrets). The test suite is large (206 files, ~2000
tests, coverage ratchet at 81 %).

It is **not yet publishable as-is**. Three issues should block a public release:

1. **OIDC account takeover by username** — an IdP identity whose `preferred_username` equals an
   existing local username (e.g. `admin`) is silently linked to, and logged in as, that local
   account.
2. **`users:write` is effectively `admin`** — permission overrides and role removal have no
   guard, so any holder of `users:write` can grant themselves every permission or strip the
   admin role from real admins. `rbac.roles:write` can rename the `admin` system role, which
   breaks every name-based admin check.
3. **The shipped Docker deployment runs as root with `ENV: development`**, which disables every
   production guard (default `SECRET_KEY`, default admin password, unverified Netmiko hosts,
   dev tools).

Everything else is medium or low and is listed with a fix in §5.

---

## 1. What was run

| Check | Result |
|---|---|
| `ruff check .` (backend) | 3 findings: 2× E501, 1× I001 |
| `scripts/check_asyncio_run.py` | OK |
| `scripts/check_http_500_leaks.py` | OK |
| `scripts/check_router_repositories.py` | OK |
| `scripts/check_text_sql.py` | OK |
| grep: f-string logging in non-test code | 0 |
| grep: bare `except:` | 0 |
| grep: `shell=True`, `yaml.load`, `eval`/`exec`/`pickle` | 0 |
| grep: `datetime.utcnow`, legacy `typing.Optional/List/Dict` | 0 |
| AST scan: classes by size and method count, functions > 80 lines, missing return annotations | see §6 |
| AST scan: every route decorator and its auth/permission dependency | see §5.2 |
| `python -m pytest` (unit, with coverage) | see §4.5 |

---

## 2. How the backend is organized

### 2.1 Size

| Metric | Value |
|---|---|
| Non-test Python files | 495 |
| Non-test lines | 56 610 |
| Test files / test functions | 206 / ~2 024 |
| Test lines | 36 620 |
| Route handlers | 238 (200 `async def`, 38 `def`) |
| SQLAlchemy models | 18 (CLAUDE.md still says 14) |
| Workflow step packages | 52 |

### 2.2 Directory map

```
backend/
├── main.py                 FastAPI app, lifespan (init_db, seed RBAC, app-scoped clients), router registration
├── start.py                uvicorn entry point
├── dependencies.py         FastAPI Depends providers (thin wrappers around service_factory)
├── service_factory.py      Process-wide singletons (Nautobot/ISE/pyATS/Mattermost clients, Redis cache, rate limiter)
├── core/
│   ├── config.py           Settings (env → typed attrs) + calls production_guards at import
│   ├── production_guards.py  Refuses default SECRET_KEY / admin password / weak DB+Redis password outside ENV=development
│   ├── auth.py             verify_token, get_current_user, require_permission/any/all, require_role
│   ├── crypto.py           Fernet + PBKDF2 key derivation for credentials at rest
│   ├── database.py         engine, SessionLocal, get_db, init_db (auto schema sync), ensure_database_exists
│   ├── safe_http_errors.py raise_internal_server_error → {message, error_id}
│   ├── safe_urls.py / safe_hosts.py  SSRF policy for outbound HTTP/git URLs and Netmiko preview hosts
│   ├── oidc_redirect.py    redirect_uri allow-list policy
│   ├── dev_tools.py        ENABLE_DEV_TOOLS gate (require_dev_tools → 404)
│   ├── logging_config.py   per-process rotating file + stdout, muted noisy loggers
│   ├── schema_manager.py / cert_installer.py / ssl_config.py
│   └── models/             SQLAlchemy tables, one file per domain, re-exported from __init__
├── models/                 Pydantic request/response schemas (one file per domain, 32 files)
├── repositories/           Data access. Most are plain classes taking a Session; BaseRepository only used by git
├── services/               Business logic, grouped by domain:
│   ├── auth/               AuthService (login/JWT), RBACService, rbac_seed, OIDCService, LoginRateLimiter
│   ├── execution/          RunService, StepRunner, graph, step_registry (dispatch table), retention, schedules
│   ├── workflow/           WorkflowService (+ git-backed version control)
│   ├── workflow_context/   attribute paths, merge, guards, secret sealing/redaction
│   ├── git/                GitService (clone/pull/push), GitRepositoryService (CRUD), auth, file/csv/debug services
│   ├── nautobot/           client + resolvers/ managers/ devices/ (facade pattern, documented in CLAUDE.md)
│   ├── ise/, pyats/, mattermost/  external-API clients + source-config services
│   ├── sources/nautobot/   inventory persistence, evaluator, live query mixin
│   ├── credentials/        CredentialsService (encrypted vault, global/private visibility)
│   ├── settings/, cache/, logging/, certificates/, system/, users/, templates/, dashboard/, health/, network/netmiko/
│   └── artifacts/          FilesystemArtifactService + sinks (filesystem, git)
├── routers/                HTTP layer. Flat files for simple domains; packages for git/, rbac/, sources/{nautobot,ise,pyats,mattermost}/, nautobot/
├── hatchet/                client, two worker entry points (live + background tier), worker_services lifespan,
│   └── workflows/          workflow_run (parent orchestration, fan-out, approval), device_group_execution (child), dispatch, schedules, retention, cache_devices
├── workflow_steps/         52 self-contained step packages ({step}/executor.py [+ config.py]), registry.yaml, common/ helpers
├── migrations/auto_schema.py  Model-vs-DB diff applied at startup
├── scripts/                regression guards, dev worker runners, ISE smoke scripts, DB sync CLI
└── tests/unit, tests/integration
```

### 2.3 Request path

```
Browser → Next.js /api/proxy/[...path] (strips Cookie/Authorization, injects Bearer from HTTP-only cookie)
        → FastAPI router (router-level Depends(get_current_user) and/or route-level Depends(require_permission(...)))
        → Service (business logic, raises DomainError subclasses)
        → Repository (SQLAlchemy 2.0 select()/Session)
```

The frontend never stores the JWT in JavaScript-readable storage. Login and refresh are Next.js
route handlers that talk to the backend and set the cookie (`httpOnly`, `sameSite=lax`,
`secure` in production). This is the correct shape for a browser client.

### 2.4 Execution path

```
POST /workflows/{id}/runs → RunService.trigger_run → WorkflowRun row (pending) → Hatchet dispatch
Hatchet live worker → workflow_run.prepare → execute_steps → StepRunner.execute_all
   → STEP_REGISTRY[step_type] → workflow_steps/{step}/executor.execute(config, context, run, artifact_service, node_id, device_sessions)
   → fan-out: child DeviceGroupExecution workflows per device batch, optional approval gate, fan-in/aggregate
```

Executors never import each other and nothing outside `services/execution/step_registry.py`
imports a step package (verified by grep). Jinja rendering uses `SandboxedEnvironment` in both
the template service and the step helper. Secrets flowing through attribute bags are sealed
with Fernet and redacted to `***REDACTED***` before persistence (`services/workflow_context/secret_fields.py`).

---

## 3. Compliance with CLAUDE.md standards

| Standard | Status | Evidence / notes |
|---|---|---|
| Model → Repository → Service → Router layering | ✅ | Every domain has all four layers; `check_router_repositories.py` passes |
| No `text()` outside allow-listed repositories | ✅ | `check_text_sql.py` passes; `ping_database` uses the documented exemption |
| No raw exception text in 5xx | ✅ | `check_http_500_leaks.py` passes; `raise_internal_server_error` used consistently |
| No `asyncio.run()` in routers | ✅ | guard passes |
| No f-string logging | ✅ | 0 occurrences |
| Models one-file-per-domain, exported from `__init__` | ✅ | 18 models; `__all__` complete |
| Tables have FKs, indexes, `created_at`/`updated_at` | ✅ | spot-checked users, rbac, credentials, workflows, runs |
| Thin routers, no business logic | ⚠️ | `routers/sources/nautobot/crud.py` builds the export document and parses the import document inline (lines ~150–280); `routers/sources/ise/ops.py` is 520 lines of repeated `try/except` mapping. Both belong in services or a shared exception handler |
| Use `BaseRepository` | ⚠️ | Only `repositories/git/git_repository_repository.py` uses it; every other repository is a standalone class with its own session. `BaseRepository` also uses legacy `session.query()` (13 call sites repo-wide) and has an optional-session pattern that duplicates every method body. Either adopt it everywhere or delete it |
| Service file naming `services/{domain}/{domain}_service.py` | ⚠️ | Mixed: `services/git/service.py`, `services/execution/run_service.py`, `services/nautobot/client.py`. Not harmful, but the CLAUDE.md rule is not followed literally |
| Workflow steps: dispatch-only registry, `ValueError` vs `RuntimeError`, `git_repository_id` via loader | ✅ | `step_registry.py` is a pure table; `classify_step_exception` maps error classes; loader used by git steps |
| Pydantic validation at boundaries | ⚠️ | All bodies are Pydantic, but only 11 models set `extra="forbid"`; unknown fields are silently dropped |
| Auth: every endpoint JWT + `require_permission` | ✅ (with 2 notes) | Every route has `get_current_user` or a permission dependency at route or router level. Only `auth/login`, `auth/refresh`, `oidc/providers|login|callback|logout` are anonymous, by design. `dashboard/layout` GET/PUT and `rbac/users/me/permissions` rely on authentication only, which is correct for per-user data |
| Rate limiting on all endpoints (global rule) | ❌ | Only `/auth/login` is rate limited |
| Files ≤ 800 lines, functions < 50 lines (global rule) | ❌ | 2 files over 800 lines; 43 functions over 80 lines (largest 259). See §6 |
| Immutability (global rule) | n/a | SQLAlchemy mutation is idiomatic and the Python rule set allows the override; frozen dataclasses are used for value objects (`OIDCConfig`, `RbacSeedResult`, `FanOutSignal` is mutable by design) |
| 80 % coverage, TDD | ✅ | Coverage ratchet `--cov-fail-under=81` enforced in `pyproject.toml` |
| Ruff | ✅ | Clean. `target-version = "py314"`; `S` (flake8-bandit) and `ASYNC` now enabled |
| Security scanning (`bandit`, dependency audit) | ✅ | ruff `S` ruleset + `pip-audit` in `.github/workflows/backend-ci.yml` (2026-09-03) |
| Docs current | ⚠️ | CLAUDE.md says 14 tables (now 18). 11 code/doc references point to `doc/FABLE-ANALYSIS.md`, which was deleted in commit `01ee1a9` |

---

## 4. Python best practices

### 4.1 Done well

- SQLAlchemy 2.0 style (`Mapped[...]`, `select()`, `db.scalar/scalars`) almost everywhere.
- `from __future__ import annotations`, PEP 604 unions, `datetime.now(UTC)`; no deprecated `utcnow`.
- Type hints on 96 % of functions (78 of 1 993 lack a return annotation).
- Domain exceptions (`core/domain_exceptions.py`) with a single FastAPI exception handler; services raise, routers translate.
- Constant-time login (`dummy_password_hash`), `secrets.token_urlsafe` for OIDC state, `PyJWKClient` for JWKS.
- `TYPE_CHECKING` imports to avoid cycles; lazy imports in `service_factory` for optional subsystems.
- Redis usage is correct: sliding-window `ZREMRANGEBYSCORE`/`ZCARD` in a pipeline with `EXPIRE`.
- Explicit `__all__`, `logging.getLogger(__name__)` everywhere, no `print()` outside `scripts/` and one flagged `noqa`.

### 4.2 Blocking work inside `async def` endpoints (most important non-security issue)

200 of 238 handlers are `async def`, yet nearly all of them call synchronous SQLAlchemy sessions,
synchronous GitPython, `subprocess.run`, `socket.getaddrinfo` (in `safe_urls`), and synchronous
Fernet/PBKDF2. FastAPI runs `async def` handlers on the event loop, so each of these calls stalls
every other in-flight request for its duration. A slow git clone, a 100 000-iteration PBKDF2
(run on every `CredentialsService()` construction, i.e. on every credentials request), or a
Postgres hiccup blocks the whole process.

Only the artifact sinks and the Netmiko session pool use `asyncio.to_thread` / `run_in_executor`.

Fix options, cheapest first:
1. Change handlers that only do sync work to plain `def` (FastAPI moves them to the threadpool).
   This is a mechanical change per router.
2. Cache the derived Fernet key once per process (`functools.lru_cache` on `_build_key`).
3. Wrap `GitService` calls and `validate_outbound_http_url(resolve_dns=True)` in `asyncio.to_thread`.
4. Long term: async SQLAlchemy with `asyncpg`, but that is a larger migration and not required
   for a first release.

### 4.3 Process-global environment mutation (`os.environ`) in request paths

`services/git/env.py::set_ssl_env` sets `GIT_SSL_NO_VERIFY=1` / `GIT_SSL_CA_INFO` in `os.environ`
for the duration of one git operation, and `services/git/auth.py` does the same with
`GIT_SSH_COMMAND`. The web process handles requests concurrently and the worker runs 10 slots.
Two overlapping git operations against different repositories will see each other's values.
Concretely, a `verify_ssl=False` repository can disable TLS verification for a concurrent
`verify_ssl=True` clone. Pass `env=` to the subprocess / GitPython call (`Repo.git.custom_environment`
or `git.Git().update_environment`) instead of mutating the process.

### 4.4 Other findings

- **Swallowed exceptions**: 13 `except ...: pass` sites (`services/git/service.py` ×4,
  `services/git/config.py` ×4, `services/cache/redis_cache_service.py` ×2, `debug_service.py` ×2,
  `file_service.py` ×1). Each should at least `logger.debug`.
- **`service_factory.build_cache_service()`** catches `Exception` and returns `None`; callers
  then silently run without cache (OIDC login returns 503, others degrade). Log the failure once.
- **`BaseRepository`** duplicates every method body for the "session supplied vs. not supplied"
  case and opens its own sessions outside the request's unit of work. It should take a `Session`
  in `__init__` like every other repository.
- **`RBACRepository.update_role` / `UserRepository.update_user`** accept `**kwargs` and
  `setattr` any attribute that exists on the model. Callers currently pass safe keys, but this is
  a mass-assignment shape; prefer explicit parameters.
- **`RBACService.has_permission`** issues 1 + 1 + N + N queries per check (permission lookup,
  override, roles, permissions-per-role), and `require_permission` plus router-level
  `get_current_user` load the `User` row twice. One `EXISTS` query joining
  `user_roles → role_permissions` would do. Not a correctness problem, but it is on every request.
- **Pydantic strictness**: add `model_config = ConfigDict(extra="forbid")` to request models
  (currently 11 of the request models have it).
- **Ruff `target-version`** ~~should be~~ **is** `py314` (2026-09-03); `S` (bandit rules) and
  `ASYNC` (blocking calls in async) are enabled. `T20` (print) and `BLE` still worth considering.
- **Static type checker**: `pyright` (basic mode) is now configured in `pyproject.toml` and runs
  in CI as an advisory job — ~149 pre-existing basic-mode findings to clear before it blocks.
- **`# noqa` count**: 62 in non-test code, mostly `E712` on boolean comparisons in SQLAlchemy
  (`== True`). Use `.is_(True)` and drop the suppressions.

### 4.5 Test suite

Unit suite run on 2026-09-02 from `backend/` with the project venv:

| Metric | Value |
|---|---|
| Tests | 2 011 passed, 0 failed, 0 skipped |
| Wall time | 24.5 s |
| Coverage | 81.45 % (22 336 statements, 4 144 missed); ratchet at 81 % |

Low-coverage areas worth attention: `workflow_steps/*/config.py` files are mostly 0 % (they are
data-only and cheap to cover), `show_summary/executor.py` 53 %, `render_jinja_template/executor.py`
77 %. Coverage of the auth/RBAC surface is high, but no test exercises the escalation paths listed
in §5.3 (S1–S3), which is why they survived.

Integration tests (real Nautobot/Gitea/Postgres/device) are opt-in and were not run.

---

## 5. Security review

### 5.1 Authentication and JWT — what is correct

- Passwords: Argon2id via `pwdlib` (`PasswordHash.recommended()`); a dummy hash is verified for
  unknown users so response time does not reveal whether a username exists.
- JWT: HS256, `algorithms=["HS256"]` pinned in every `jwt.decode` (no `alg=none` confusion),
  `exp` present, `user_id` type-checked (`isinstance(..., int)`).
- Token transport: never in JS-readable storage. Next.js sets an `httpOnly`, `sameSite=lax`,
  `secure`(prod) cookie and injects the `Authorization` header server-side; incoming `Cookie` and
  `Authorization` headers are stripped before forwarding, `Set-Cookie`/`Location` stripped on the
  way back. The proxy rejects `.`/`..`/empty path segments.
- Deactivated users are rejected by `get_current_user` **and** by every `require_*` dependency
  (`_require_active_user_id`), so deactivation takes effect on the next request even with a live
  JWT.
- Refresh (`/auth/refresh`) verifies the signature, tolerates `exp` only up to
  `REFRESH_TOKEN_MAX_AGE_HOURS` after expiry, and re-checks `is_active` and that `sub` still
  matches the username.
- Login rate limiting: Redis sliding window, 5 attempts / 60 s per `client_ip:username`,
  `X-Forwarded-For` only honoured from `TRUSTED_PROXY_IPS`, fail-closed outside development.
- Production guards refuse to start outside `ENV=development` with default `SECRET_KEY`, default
  admin password, `CREDENTIAL_ENCRYPTION_KEY` missing or equal to `SECRET_KEY`, weak DB password,
  empty Redis password, dev tools on, or arbitrary Netmiko hosts.
- OpenAPI docs are off by default outside development.

### 5.2 Authorization / RBAC — what is correct

- Every route carries a permission dependency at route or router level except the intentionally
  anonymous auth/OIDC endpoints and two "own data" endpoints (`dashboard/layout`,
  `rbac/users/me/permissions`). Verified by walking every route decorator with an AST script.
- Precedence is implemented exactly as documented: user override (allow or deny) → role grant → deny.
- Object-level checks exist where they matter: workflows and runs (`visibility == private` and
  `creator_id`), credentials (`get_by_id_for_user` returns `None` for other users' private rows,
  avoiding existence leaks), inventories (`created_by` scope), git steps only resolve global credentials.
- `credentials:reveal` is a separate permission from `credentials:read`.
- Destructive/dev endpoints (`system/schema/migrate`, `system/rbac/seed`, `certificates/add-to-system`,
  all `git/*/debug/*`) are double-gated by `require_dev_tools` (404 when off) and a permission.
- System roles cannot be deleted; assigning a *system* role or changing a *system* role's
  permissions requires the actor to hold `admin`.

### 5.3 Findings

Severity: **H** = fix before publishing, **M** = fix in the first hardening pass, **L** = backlog.

| # | Sev | Area | Finding | Location | Fix | Status |
|---|---|---|---|---|---|---|
| S1 | **H** | OIDC | **Account takeover by username.** `provision_or_get_user` looks up the local user by the `preferred_username` claim and, if found and active, updates `oidc_provider` and logs the caller in. Any IdP identity that can present `preferred_username=admin` (self-registration IdPs, multi-tenant IdPs, user-editable profile fields, or a second configured provider) becomes the local `admin`. The `sub` claim is extracted but never stored or compared. | `services/auth/oidc_service.py::provision_or_get_user` | Store `(oidc_provider, oidc_subject)` on `User` (unique together). Match existing users by `(provider, sub)` first. When only a username match exists: refuse to link if `existing.oidc_provider` is `None` (local account) or a different provider, unless an admin explicitly links it. Never mutate `oidc_provider` on a login path. | **Fixed** (47ea5be) — bind by `(oidc_provider, oidc_subject)`; `OIDCIdentityConflictError` on username collision. |
| S2 | **H** | RBAC | **`users:write` escalates to full admin.** `POST /rbac/users/{id}/permissions` (override) has no guard, so a `users:write` holder can grant *themselves* `rbac.roles:write`, `users:delete`, `system.*`, and every other permission via overrides. `DELETE /rbac/users/{id}/roles/{role_id}` has no system-role guard, so the same holder can strip `admin` from every real admin. `assign_role_to_user` only guards *system* roles, so a self-created role holding all permissions can be self-assigned. | `routers/rbac/user_access.py`, `services/auth/rbac_service.py` | (a) Overrides and role assignment that would grant a permission the *actor* does not hold must be refused (no delegation beyond own rights). (b) Removing a system role and writing overrides that touch `rbac.*`, `users.*`, `system.*` require `admin`. (c) Forbid acting on your own user id for role/override changes. (d) Refuse to remove the last admin. | **Fixed** (d9eec94) — RBAC grant policy P1-P7 in `RBACService`/`UserService`. |
| S3 | **H** | RBAC | **System roles can be renamed.** `PUT /rbac/roles/{id}` calls `update_role(name=...)` with no `is_system` check. Renaming `admin` breaks `has_role(user, "admin")`, `_require_admin_actor`, the lifespan re-grant, and `SYSTEM_ROLES` seeding (which will then create a *new* empty `admin` role). | `routers/rbac/roles.py::update_role`, `RBACService.update_role` | Reject `name` changes when `role.is_system`; allow description only. Better: check admin by `is_system` + a stable key rather than by display name. | **Fixed** (d9eec94) — P5: system roles reject a `name` change in `RBACService.update_role`. |
| S4 | **H** | Deploy | **Shipped containers run as root and default to an insecure configuration.** None of `docker/Dockerfile.basic`, `Dockerfile.worker`, `Dockerfile.all-in-one` declare a `USER`. The `x-manus-app-env` anchor in `docker/docker-compose.yml` hard-codes `ENV: development`, `SECRET_KEY: change-in-production-use-at-least-32-characters`, `INITIAL_PASSWORD: admin`, `DOCS_ENABLED: "true"`, and `CREDENTIAL_ENCRYPTION_KEY: ""`. Because `ENV=development`, every guard in `core/production_guards.py` is skipped, so this stack starts and serves with the default JWT signing key (anyone can mint admin tokens), `admin/admin`, and public OpenAPI docs. `docker/DOCKER.md` mentions `ENV=production`, but the defaults are what people run. | `docker/*` | Add a non-root `USER` (the `update-ca-certificates` path is already dev-tools-gated). Remove secret defaults from compose (`${SECRET_KEY:?set in .env}`), default to `ENV: production`, and move the development values into a separate `docker-compose.dev.yml` override. | **Fixed** (d3dbb51, e80df04) — non-root `manus` user in all three images; compose secrets required via `docker/.env`; guards reject a short `SECRET_KEY`/`INITIAL_PASSWORD` outside development. |
| S5 | M | JWT | **No server-side revocation and no absolute session lifetime.** Logout only clears the cookie; the token stays valid until `exp`. Refresh accepts a token up to 24 h *after* expiry and issues a fresh 60-minute token, so a stolen token that is refreshed once a day lives forever. Password change or username change by an admin does not invalidate existing tokens. No `iat`, `jti`, `iss`, or `aud` claims. | `services/auth/auth_service.py` | Add `iat` and `jti`. Store `token_version` (or `password_changed_at`) on `User`; embed it in the token and compare on `verify_token`; bump it on password change, username change, deactivation, and logout. Add an absolute cap (e.g. `SESSION_MAX_AGE_HOURS`) enforced from the original `iat` carried through refreshes. Optionally keep a Redis denylist keyed by `jti` for explicit logout. | **Fixed** (d264af6, dcf30db, c304045) — `users.token_version` + `iat`/`jti`/`sid_iat` claims; bumped on logout / password / username change / deactivation; `SESSION_MAX_AGE_HOURS` absolute cap; change-password returns a fresh session. Plan: `doc/plans/FABLE_BACKEND_S5_S7_S12_S13.md`. |
| S6 | M | Passwords | **No password policy.** `UserCreate`/`UserUpdate` require `min_length=1`. There is no self-service password change (only `users:write` can set passwords) and no forced change of the bootstrap password. | `models/rbac.py`, `routers/users.py` | Enforce a minimum length (12+) and reject the top common passwords; add `POST /auth/change-password` requiring the current password; flag `must_change_password` on the seeded admin. | **Fixed** (e80df04, ad04532, 75895c5) — `password_policy.py`, `POST /auth/change-password`, `must_change_password` enforced server-side. |
| S7 | M | Git | **Cross-request TLS/SSH env leakage** (see §4.3): `GIT_SSL_NO_VERIFY=1` set for one repository applies to concurrent git subprocesses of other repositories. | `services/git/env.py`, `services/git/auth.py` | Pass a per-call environment to GitPython/subprocess instead of mutating `os.environ`. | **Fixed** (cd709d4) — `set_ssl_env` replaced by pure `build_git_env_overrides` / `merge_git_environ`; `env=` passed to `Repo.clone_from` and `repo.git.custom_environment`. |
| S8 | M | Path handling | `GitFileService` guards traversal with `resolved.startswith(repo_path_resolved)` (three copies). `/data/repos/foo` also matches `/data/repos/foo-other`. Repository paths are admin-defined so exploitation needs an adjacent repo, but the check is wrong. | `services/git/file_service.py` lines ~135, ~500, ~551, ~612 | Use `Path.is_relative_to` (or `os.path.commonpath`) once in a helper and reuse it. | **Fixed** (1184086) — `services/git/paths.py::resolve_within_repo` (`Path.is_relative_to`) replaces all 5 string-prefix checks (4 in `file_service.py`, 1 in `csv_service.py`). |
| S9 | M | Availability | **No rate limiting beyond login.** Expensive endpoints (`netmiko/run-commands`, `sources/ise/*`, `sources/nautobot/*/analyze`, `git/*/sync`, `templates/render`) can be hammered by any authenticated user. The login limiter is fail-closed outside development, so a Redis outage is a total login outage. | `main.py` | Add a generic per-user limiter middleware (Redis token bucket) with higher budgets; document the Redis dependency for login or fail-open with a per-process fallback plus alerting. | Open |
| S10 | M | Bootstrap | **Bootstrap admin is re-granted `admin` on every start.** `lifespan` calls `assign_role_to_user_by_name(admin_user.id, "admin")` unconditionally, so demoting or restricting `INITIAL_USERNAME` is undone by a restart. `INITIAL_PASSWORD` is only used on first creation, which is fine. | `main.py::lifespan` | Only assign on first creation (when `ensure_initial_admin` actually created the row) or when no admin exists. | **Fixed** (1184086) — `main.py` lifespan (and `admin_reseed_rbac`'s non-wipe path) grant `admin` only when `RBACService.role_has_members("admin")` is false: first boot and total-loss self-heal still work, a deliberate demotion survives while another admin remains. |
| S11 | M | Schema | **DDL at startup with no lock.** `init_db` creates tables/columns/indexes on every boot. Two web replicas starting together race on `CREATE TABLE`. | `core/database.py`, `migrations/auto_schema.py` | Wrap in `pg_advisory_lock`, or move to explicit migrations (Alembic) before scaling out. | **Fixed** (1184086) — `init_db` holds `pg_advisory_xact_lock` (transaction-scoped, auto-released) around the schema sync so replica boots serialize; `ensure_database_exists` swallows `psycopg.errors.DuplicateDatabase`. Alembic still recommended before scaling out. |
| S12 | L | Secrets | `SECRET_KEY` is only checked for inequality with the default; no minimum length or entropy check. `KDF_ITERATIONS` is read from raw `os.getenv` in `core/crypto.py` instead of `Settings`. Static KDF salt is acceptable for a high-entropy secret but should be documented. | `core/config.py`, `core/crypto.py` | Require ≥ 32 bytes; move `KDF_ITERATIONS` into `Settings`; derive the Fernet key once per process. | **Fixed** (e1382fc) — `SECRET_KEY` ≥ 32 already shipped (S4/S6); `KDF_ITERATIONS` now via `Settings` with a 100000 floor; `_build_key` `lru_cache`d; static salt documented in `doc/SECURITY-NOTES.md`. |
| S13 | L | OIDC | No `nonce` in the authorization request / ID-token check and no PKCE. `client_secret` lives in `config/oidc_providers.yaml` on disk. `test-login` allows overriding `client_id` (dev-tools gated). | `services/auth/oidc_service.py` | Add `nonce` (store with state in Redis, verify claim), add PKCE `code_verifier`. Allow `client_secret` from env (`OIDC_<PROVIDER>_CLIENT_SECRET`). | **Fixed** (bb80ef9) — `nonce` + S256 PKCE on the auth request and verified on callback; `client_secret` from `OIDC_<PROVIDER_ID>_CLIENT_SECRET` (YAML fallback), empty → `OIDCError`. |
| S14 | L | Ownership | Inventories are owned by `created_by: str` (username), not a FK. Renaming a user (allowed via `users:write`) orphans their private inventories, and renaming yourself to a former username inherits that user's private inventories. | `core/models/inventories.py` | Add `owner_user_id` FK like `credentials` did; keep the string for display. | Open |
| S15 | L | Uploads | Certificate upload reads the whole file into memory with no size cap; general request-body limit is not configured. | `services/certificates/certificate_service.py` | Cap at e.g. 64 KiB for PEM; set a global body limit at the reverse proxy. | Open |
| S16 | L | Info | `oidc/debug` (dev-tools + permission gated) returns `client_id`, discovery URLs, config path. Fine while dev-tools gated; keep it that way. | — | — | Open |

Accepted risks already documented in `doc/SECURITY-NOTES.md` (Netmiko host-key checking off,
`verify_ssl=False` support, git credentials in argv, pyATS shim over plain HTTP) were re-checked
and remain accurately described. The git argv exposure could be closed with `GIT_ASKPASS`; the
others are reasonable for a managed internal network.

### 5.4 Things that were checked and are fine

- SSRF: `core/safe_urls.py` blocks non-http(s) schemes, userinfo, loopback (unless opted in),
  link-local, multicast, unspecified, the GCP metadata hostname, and resolves DNS to check every
  A/AAAA record. Git remotes additionally reject `file://` and bare paths. Netmiko preview hosts
  are denied outside development unless explicitly allowed.
- Template injection: both Jinja environments are `SandboxedEnvironment`.
- Command injection: no `shell=True`; `subprocess.run` receives argv lists; `update-ca-certificates`
  takes no user input; certificate filenames are regex-validated after `Path(...).name`.
- Deserialization: `yaml.safe_load` only; no `pickle`, `eval`, `exec`.
- SQL: SQLAlchemy Core/ORM everywhere; `CREATE DATABASE` uses `psycopg.sql.Identifier` and the
  name is regex-validated.
- Secrets in logs: grep found only "present/None" and "decrypted for '<name>'" style messages, no
  values. Attribute-bag secrets are sealed and redacted before persistence.
- Error leakage: all router 5xx paths go through `raise_internal_server_error`; 4xx `detail=str(exc)`
  is used only for domain/validation errors that carry no internals.

---

## 6. Refactoring candidates

### 6.1 Files over the 800-line limit

| File | Lines | What it contains | Suggested split |
|---|---|---|---|
| `hatchet/workflows/workflow_run.py` | 959 | prepare, debug pauses, phase-1 execution, fan-out dispatch plan parsing, child input building, batch approval wait/resume, aggregation + persistence | `workflow_run.py` (task definitions only), `fan_out_dispatch.py`, `batch_approval.py`, `aggregate.py` |
| `services/execution/step_runner.py` | 894 | `StepRunner` (804 lines, 25 methods): graph loading + funnel resolution + plan building, pending result creation, upstream-failure blocking, node execution + persistence, join/resume, subgraph execution, context assembly, serialization | `ExecutionPlanner` (load/filter/funnels/topological), `NodeExecutor` (execute + persist one node), `SubgraphRunner` (fan-out children / resume-after-join), keep `StepRunner` as a thin façade |

### 6.2 God-object candidates

| Class | Lines / methods | Assessment |
|---|---|---|
| `StepRunner` | 804 / 25 | **Yes.** Owns planning, execution, persistence, session pool lifecycle, and serialization. Split as above. |
| `DeviceCommonService` | 392 / 43 | Facade by design (CLAUDE.md says so). 43 pass-through methods is at the limit; consider exposing the resolvers/managers as attributes (`common.devices.resolve_by_name(...)`) instead of re-wrapping every method. |
| `RBACService` | 166 / 30 | Not a god object (thin passthroughs), but the authorization *policy* (who may grant what) is missing from it, which is the root of S2/S3. Add it here, not in routers. |
| `InterfaceManagerService` | 635 / 13 | Large but cohesive. `_assign_ip_to_interface` (88 lines) and the update flow should be broken into steps. |
| `DeviceUpdateService` | 616 / 16 | `update_device` is 147 lines. Extract per-field-group updaters. |
| `GitService` | 483 / 9 | `push` is 102 lines; four `except: pass`. Extract commit/push helpers already partly in `common/git_push_helpers.py`. |
| `GitFileService` | 421 / 9 | Path-resolution block duplicated three times (S8). |
| `RedisCacheService` | 448 / 14 | `stats` is 92 lines; fine otherwise. |
| `NetmikoDeviceSession` | 314 / 21 | Cohesive; OK. |

### 6.3 Long functions (over 80 lines; 43 total)

Top offenders and what to do:

| Function | Lines | Note |
|---|---|---|
| `workflow_steps/configure_replace_config/executor.py::_process_one_device` | 259 | Sequence of phases (backup, upload, replace, verify, rollback). One function per phase returning a small result dataclass. |
| `workflow_steps/compare_pyats_snapshot/executor.py::_compare_one_device` | 173 | Same pattern. |
| `workflow_steps/notify_on_error/executor.py::execute` | 147 | Message building vs. sending. |
| `services/nautobot/devices/update.py::update_device` | 147 | Per-field-group updaters. |
| `services/git/connection.py::test_connection` | 126 | Auth resolution / reachability / branch listing as separate steps. |
| `services/git/auth.py::_resolve_from_manager` | 110 | Table-driven by `auth_type`. |
| `hatchet/workflows/workflow_run.py::_aggregate_and_persist` | 109 | Move to `aggregate.py`. |
| `services/git/service.py::push` | 102 | See above. |

Nineteen step executors exceed 300 lines. They are self-contained by design, so size alone is not
a problem, but the 400–700-line ones (`configure_replace_config`, `deploy_rendered_template`,
`compare_data`, `compare_pyats_snapshot`, `run_command`, `get_ise_tacacs_key`, `add_to_ise`) each
hide a per-device state machine that would be easier to test as small functions.

### 6.4 Duplication and boilerplate

- `routers/sources/ise/ops.py` (520 lines) and `routers/sources/nautobot/ops.py` (406 lines)
  repeat the same `try/except ISEValidationError/ISEAPIError/HTTPException/Exception` block in
  every handler. Register `@app.exception_handler` for `ISEAPIError` (→ 502 sanitized) and
  `ISEValidationError` (→ 400) and delete ~250 lines.
- `routers/sources/nautobot/crud.py`: move export/import document building into
  `InventoryService` (or a new `inventory_transfer.py`) so the router is a thin delegate.
- `core/auth.py`: `get_current_user` and `_require_active_user_id` are the same check; have
  `require_permission` depend on `get_current_user` and reuse the loaded `User`.
- `repositories/base.py`: delete or adopt (see §3).

### 6.5 Housekeeping

- Remove the 11 dangling references to `doc/FABLE-ANALYSIS.md` (in `services/auth/auth_service.py`,
  `login_rate_limiter.py`, `doc/SECURITY-NOTES.md`, and others) or restore the file under
  `doc/analysis/`.
- Update CLAUDE.md: 18 models (add `background_tier`, `notifications`, `schedules`,
  `user_preferences`), and add `core/production_guards.py`, `safe_urls.py`, `safe_hosts.py`,
  `oidc_redirect.py`, `dev_tools.py` to the "Backend Core" list since they are security-relevant
  entry points a new contributor must know about.
- `scripts/ise_test*.py` (8 files) are manual smoke scripts using `print`; move them under
  `tests/integration` or `scripts/manual/` so they are clearly not part of the app.

---

## 7. Recommended order of work

**Before publishing (blockers)**

1. S1 — bind OIDC users by `(provider, sub)`; never auto-link an existing local account.
2. S2 + S3 — put the grant policy into `RBACService`: no delegation beyond own rights, admin
   required for anything touching `rbac.*`/`users.*`/`system.*`, no self-modification, no
   renaming/deleting system roles, never remove the last admin. Add tests for each rule.
3. S4 — non-root `USER` in all three Dockerfiles; compose defaults to `ENV=production`.
4. S6 — minimum password length; self-service password change; force change of the seeded
   admin password.

**First hardening pass (1–2 weeks)**

5. S5 — `iat`/`jti`/`token_version`, absolute session lifetime, invalidate on password/username
   change and logout. **Done.**
6. S7 — stop mutating `os.environ` in git code. **Done.**
7. §4.2 — convert sync-only handlers to `def`, ~~cache the Fernet key~~ (already done in S12),
   thread-offload git and DNS. **Done (2026-09-03, `doc/plans/FABLE_REST.md`)** — handlers in
   29 router modules are now `def`; DNS in the async source clients goes through
   `validate_outbound_http_url_async`. Git offload was already covered by making the git
   routers `def` (threadpool) plus the pre-existing `run_in_executor` in `git/devices.py`.
8. S8, S10, S11 — path check helper, bootstrap-admin re-grant, advisory lock around `init_db`.
   **Done.**
9. Add ~~`bandit`~~/ruff `S` rules, `pip-audit`, and `pyright` to a CI workflow that also runs
   the four guard scripts and the test suite. **Done (2026-09-03)** —
   `.github/workflows/backend-ci.yml`. ruff `S` replaces standalone bandit (bandit ≤ 1.9.4
   crashes on the Python 3.14 AST and uses a separate `# nosec` syntax).

**Backlog**

10. Split `workflow_run.py` and `StepRunner`; shrink the eight functions over 100 lines.
11. S9 generic rate limiting; S12–S15.
12. Documentation and housekeeping in §6.5.
