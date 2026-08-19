# Backend Analysis — Grok 4.6

**Date:** 2026-08-19  
**Scope:** `/backend` only (473 non-test Python files). Frontend, Docker, and infra are out of scope except where they affect backend security (proxy-only access, Redis, Hatchet).  
**Standards:** `CLAUDE.md` architectural rules, plus the security checklist in that file.  
**Method:** Static review of routers, services, repositories, models, Hatchet workflows, workflow steps, regression scripts, and targeted verification of high-impact findings.

This document records **violations of project standards**, **security risks**, **oversized modules**, and **dead code**. Accepted risks already documented in `doc/SECURITY-NOTES.md` are restated briefly so they are not treated as new discoveries.

---

## 1. Executive summary

The backend is in **good structural health** relative to `CLAUDE.md`:

- Production database is PostgreSQL only; SQLite is confined to unit tests.
- Local DB access goes through repositories. Routers do not import repositories (`scripts/check_router_repositories.py` is green).
- `sqlalchemy.text()` is confined to the documented allow-list (`scripts/check_text_sql.py` is green).
- Router 5xx responses are sanitized (`scripts/check_http_500_leaks.py` is green).
- JWT payloads do not embed permissions; RBAC is evaluated per request.
- No CORS on the FastAPI app (proxy-only frontend pattern).
- Celery is gone at runtime; Hatchet is the orchestrator.
- No SQL injection, pickle, `eval`/`exec`, `yaml.load`, or `shell=True` command injection found.

The main gaps are **layering** (fat routers, FastAPI `HTTPException` inside services) and **security hardening** that `CLAUDE.md` does not fully cover: Git SSH host-key checking is off, SSH git remotes skip SSRF IP checks, RBAC assignment has no anti-elevation guard, and `ENABLE_DEV_TOOLS` is not blocked outside development.

`CLAUDE.md` itself is **stale** in a few places (table count, Celery wording, Python version). Those drifts are listed in §7.

---

## 2. Compliance scorecard vs `CLAUDE.md`

| Rule | Status | Notes |
|------|--------|--------|
| Model → Pydantic → Repository → Service → Router | **Partial** | Domain CRUD is layered. Git ops, Netmiko preview, Nautobot/ISE ops, and system/schema routes skip or thicken the service layer. |
| Thin routers | **Partial** | Several source and git routers contain orchestration. |
| Never bypass repository for local DB | **Pass** | Git uses a repository, but with self-managed sessions (see §3.5). |
| No `text()` in routers/services | **Pass** | Allow-list only: `core/database.py`, schema tooling, `scripts/database/sync.py`. |
| No f-string logging | **Pass** | Logging uses `%`-style formatting. |
| Sanitized 5xx (`raise_internal_server_error`) | **Pass** (routers); **Partial** (services) | Router guard is green. Services still raise raw `HTTPException(500)` or return `str(e)`. |
| JWT auth on endpoints | **Pass** | Exceptions: `/health`, `/health/ready`, OIDC login/callback/providers (by design). |
| `require_permission()` on endpoints | **Partial** | Dashboard is JWT-only. |
| `workflow_steps` isolation (only StepRunner calls executors) | **Partial** | `step_registry.py` is a dispatch table (allowed). The workflow-steps **router** dynamically loads `config.py`. |
| Models exported from `core/models/__init__.py` | **Pass** | All 17 tables exported. |
| Indexes, FKs, timestamps | **Mostly pass** | Junction/audit tables omit `updated_at` (reasonable). `GitRepository` still uses legacy `Column()`. |
| PostgreSQL production | **Pass** | |
| No Celery runtime | **Pass** | Stale comments remain. |
| No CORS | **Pass** | |
| Pydantic validation | **Pass** | One inline model in a router. |
| No God-object services | **Partial** | `DeviceCommonService` is a documented facade. `step_runner.py` and `file_service.py` are not. |

---

## 3. Standard violations

Findings are ordered by impact on the architecture, not by file size.

### 3.1 Services raise FastAPI `HTTPException` (high)

`CLAUDE.md` requires business logic in services and HTTP mapping in routers. At least **83** `raise HTTPException` call sites live under `backend/services/`:

| Service | Approximate count |
|---------|------------------:|
| `services/git/file_service.py` | 28 |
| `services/execution/run_service.py` | 18 |
| `services/settings/settings_service.py` | 11 |
| `services/workflow/workflow_service.py` | 10 |
| `services/execution/schedule_service.py` | 7 |
| `services/git/csv_service.py` | 7 |
| `services/git/shared_utils.py` | 2 |

Example (`services/execution/run_service.py` and `services/workflow/workflow_service.py`):

```python
raise HTTPException(status_code=404, detail="Workflow not found")
raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Workflow created but could not be retrieved")
```

**Why it matters:** Services become unusable outside FastAPI (Hatchet workers, scripts, tests). A domain exception hierarchy (`NotFoundError`, `AccessDeniedError`, `ConflictError`) mapped in routers (or a shared exception handler) would restore the layer boundary.

**Remediation:** Introduce domain exceptions; keep `HTTPException` in routers and `core/auth.py` only. Use `raise_internal_server_error` for every 5xx.

### 3.2 Fat routers with business logic (high)

**Git operations** (`routers/git/operations.py`, ~191 lines of handler logic): load repo, update sync status, call operations service, invalidate cache, persist error IDs. That orchestration belongs in `GitOperationsService`.

**Netmiko preview** (`routers/netmiko.py`, lines 55–222): host policy, credential lookup, password decrypt, `DeviceSessionPool` lifecycle, `NetmikoService.send_commands`, response shaping. This is a preview **service**, not a router.

**Nautobot / git source ops** (`routers/sources/nautobot/ops.py`, `routers/sources/git/ops.py`): settings lookup + credential assembly + external API call inline. Same pattern in ISE ops.

**System router** (`routers/system.py` lines 27–55): instantiates `SchemaManager` and calls `admin_reseed_rbac` directly. There is no `SystemService`.

**Templates router** (`routers/templates.py` lines 40–54): `_assert_credential_visible` is authorization logic that belongs in `TemplatesService`.

**Largest router files (should be thin):**

| File | Lines |
|------|------:|
| `routers/sources/ise/ops.py` | 570 |
| `routers/sources/nautobot/ops.py` | 551 |
| `routers/sources/nautobot/crud.py` | 369 |

ISE/Nautobot ops routers are the clearest `CLAUDE.md` violations: HTTP handlers performing connection tests, device CRUD, NDG CRUD, search, and preview.

### 3.3 Dashboard missing `require_permission()` (medium)

`routers/dashboard.py` authenticates with `get_current_user` only. Layout, schedules, recent runs, and notifications have **no** `require_permission()`.

Queries are visibility-scoped (`public` OR `creator_id == user_id`) in `ScheduleRepository.list_enabled_with_workflow`, `RunRepository.list_recent_runs`, and `NotificationRepository.list_recent`. This is **not** a full IDOR, but it **does** violate the rule that endpoints check `{resource}:{action}`.

Any logged-in user with **no** `workflow_runs:read` / `workflows:read` can still see public workflow schedules, recent public runs, and related notifications.

**Remediation:** Add dashboard (or reuse workflow/run) permissions, or document an explicit “authenticated-user home feed” exception in `CLAUDE.md`.

### 3.4 `workflow_steps` config loaded outside StepRunner (medium)

`CLAUDE.md`: *External code must never import `workflow_steps` packages directly; only StepRunner calls executors.*

`routers/workflow_steps.py` (lines 73–94) dynamically loads `workflow_steps/{directory}/config.py` via `importlib` and calls `get_config()`. That is not executor invocation, but it still reaches into step packages from a router.

`services/execution/step_registry.py` importing executors is **compliant** (dispatch table only). Unit tests importing executors are an acceptable exception.

**Remediation:** Load configs through `PluginRegistryService` (or a dedicated config registry) at startup, the same way executors are registered.

Also: `PluginConfigResponse` is defined inline in that router (lines 33–36). Pydantic models belong in `backend/models/`.

### 3.5 Git repository layer uses self-managed sessions (medium)

Most services take a request-scoped `Session` (`get_db`). `GitRepositoryService` constructs `GitRepositoryRepository()` with **no** session (`services/git/repository_service.py:26–27`). `BaseRepository._db_session()` then opens and closes its own connection per call.

This still uses the repository pattern, but:

- Git CRUD cannot share a transaction with other work in the same request.
- It is inconsistent with `WorkflowService`, `RunService`, `AuthService`, etc.

`git_repo_manager` is a module-level singleton (`services/git/shared_utils.py`), aliased as `GitRepositoryManager` even though the class is `GitRepositoryService`.

### 3.6 5xx / error payload hygiene in services (medium)

Router 5xx leaks are guarded. Services are not:

| Location | Issue |
|----------|--------|
| `services/workflow/workflow_service.py:145–158` | `HTTPException(500, detail="...")` without `error_id`; bare `raise` on unexpected failure |
| `services/git/repository_service.py:168–170` | Health payload returns `"error": str(e)` (endpoint is authenticated: `git.repositories:read`) |
| `services/git/file_service.py:483–487, 605–608` | 4xx `detail=f"... {str(e)}"` (Git internals) |
| `services/git/connection.py:152–158` | Connection-test message interpolates `str(e)` |

`CLAUDE.md` is explicit about 5xx. The 4xx cases are weaker but still leak implementation details to clients.

### 3.7 Stale Celery wording (low)

No Celery imports, tasks, or dependency. Remaining mentions:

- `hatchet/workflows/cache_devices.py:6–7` (historical comment)
- `utils/inventory_converter.py:10, 180` (docstring)
- `CLAUDE.md` still says “Never call `text()` from … or Celery tasks” and “Python/Celery projects”

Harmless, but it misleads new contributors.

### 3.8 Model / naming nits (low)

- `GitRepository` (`core/models/git.py`) uses imperative `Column()` instead of `Mapped[]` used by every other domain model.
- `Notification` has `created_at` only — reasonable for an immutable audit row.
- RBAC junction tables (`role_permissions`, `user_roles`, `user_permissions`) and `permissions` have `created_at` only.
- `GitRepositoryManager` alias vs `GitRepositoryService` class name.

None of these break runtime behaviour.

---

## 4. Security risks

No **critical** issues were confirmed (no unauthenticated RCE, no SQL injection, no unauthenticated secret dump).

Items already recorded as **accepted** in `doc/SECURITY-NOTES.md` are marked **(accepted)**. New or under-documented items are unmarked.

### 4.1 High

#### Git SSH host-key verification disabled

`services/git/connection.py:282–285` and `services/git/auth.py:286–288`:

```python
env["GIT_SSH_COMMAND"] = (
    f'ssh -i "{ssh_key_path}" '
    "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
)
```

`auth.py` also sets `StrictHostKeyChecking=no` (without discarding `known_hosts`). A MITM on the path to the git server can serve a malicious repo. Netmiko’s equivalent gap is **accepted** in `SECURITY-NOTES.md`; Git SSH is **not** listed there and should be treated as a separate, higher-impact issue because clone content is executed as workflow input and can be pushed back.

**Remediation:** Persist `known_hosts` (or `accept-new` with a dedicated file). Do not use `/dev/null`.

#### SSH git remotes skip SSRF / IP policy

`core/safe_urls.py:79–99`: HTTPS remotes go through `validate_outbound_http_url()` (DNS + IP allow/deny). `ssh` / `git+ssh` / scp-like URLs only require a non-empty hostname.

An authenticated user who can configure a git source can point the backend at `git@10.0.0.5:…` or a link-local/metadata host. Clone/sync runs **from the server**.

**Remediation:** Resolve SSH hostnames and apply the same IP policy as HTTP URLs.

#### RBAC role assignment has no elevation guard

`routers/rbac/user_access.py:77–93`: any principal with `users:write` can `POST /rbac/users/{id}/roles` with the admin role. `rbac.roles:write` can attach arbitrary permissions to any role. System roles are protected from **deletion**, not from **assignment**.

This is privilege escalation if `users:write` is granted more broadly than “user admin who may mint admins.”

**Remediation:** Restrict admin-role assignment (dedicated permission or `require_role("admin")`); block self-elevation; optionally require two-person approval for `is_system` roles.

### 4.2 Medium

#### `ENABLE_DEV_TOOLS` not refused outside development

`core/production_guards.py` rejects default `SECRET_KEY`, `admin` password, missing/equal encryption key, and weak DB passwords. It does **not** reject `ENABLE_DEV_TOOLS`.

When set, that flag exposes git debug write/push tests, schema migrate, RBAC reseed, certificate install, and OIDC test-login (`core/dev_tools.py`, `routers/git/main.py`, `routers/system.py`, `routers/oidc.py`). Routes still require RBAC, but a production misconfiguration turns on break-glass tooling.

**Remediation:** Fail startup if `ENABLE_DEV_TOOLS` is set when `ENV != development`.

#### OIDC test-login can skip redirect allowlist

`routers/oidc.py` + `core/oidc_redirect.py`: `initiate_test_login` uses `relax_redirect=True` when dev tools are on. Combined with the previous item, a production mis-set flag weakens open-redirect protection.

**Remediation:** Never relax redirect validation. Keep test-login on an explicit localhost allowlist.

#### TLS verification optional on outbound integrations **(accepted for Nautobot/ISE)**

`verify_ssl=False` exists for Nautobot, ISE, Mattermost, PyATS, and git HTTPS (`GIT_SSL_NO_VERIFY=1` in `services/git/env.py:39–40`). `SECURITY-NOTES.md` accepts this for Nautobot/ISE with WARNING logs. Mattermost/PyATS/git HTTPS should be treated the same or gated.

#### Netmiko preview to arbitrary hosts **(partially accepted)**

`core/safe_hosts.py` blocks loopback, link-local, multicast, unspecified, and a couple of metadata hostnames. Outside development, arbitrary hosts require `ALLOW_NETMIKO_ARBITRARY_HOSTS=true` (defaults to true only in development — `core/config.py:116–118`). RFC1918 addresses are **not** blocked when the flag is on. Host-key checking is off (**accepted** in `SECURITY-NOTES.md`).

#### Login rate limiter degrades when Redis is down

`services/auth/login_rate_limiter.py:50–58`: Redis errors fall back to **per-process** counters (5 / 60s). Multi-worker deployments then allow ~5 × worker count attempts. Default Redis URL has no password (`redis://localhost:6379/0`).

**Remediation:** Require Redis auth outside development; consider fail-closed for login, or a shared fallback.

#### `X-Forwarded-For` trust

`routers/auth.py` uses forwarded headers only when `request.client.host` is in `TRUSTED_PROXY_IPS`. Correct design; still easy to misconfigure (too broad → IP spoof / rate-limit bypass; empty behind a proxy → one shared bucket).

#### Workflow run outputs can hold secrets

`services/workflow_context/secret_fields.py` redacts known sealed paths. The module comments that secrets copied into arbitrary output shapes are **not** redacted. `workflow_runs:read` returns `step_results[].output` (command output, configs, diffs).

Private workflows are creator-scoped. Public workflows are visible to anyone with read permission — by design, but a tenancy risk.

#### Git credentials in process argv **(accepted)**

Documented in `SECURITY-NOTES.md`: HTTPS basic-auth in `git clone` argv is visible via `ps` for the duration of the subprocess.

#### pyATS shim credentials over HTTP **(accepted)**

Documented in `SECURITY-NOTES.md`: only on the internal Docker network.

### 4.3 Low

| Item | Detail |
|------|--------|
| Unauthenticated `/health` and `/health/ready` | Standard. Ready reports DB/Redis up/down (`unavailable` / `unconfigured`), not exception text. |
| Public `GET /auth/oidc/providers` | SSO discovery; expected. |
| Default dev secrets | Blocked in non-development by `production_guards.py`. Unsafe if `ENV=development` is reachable. |
| SSH keys written to `data/ssh_keys/` mode `0o600` | `credentials_service.py:234–246`. Backup/compromise of the data dir exposes keys. |
| Certificate upload unbounded `await file.read()` | DoS for `system.certificates:write`. Cap PEM size. |
| Fixed PBKDF2 salt `auxilium-credential-encryption-v1` | `core/crypto.py:12–13`. Weakens offline brute-force if ciphertext and `CREDENTIAL_ENCRYPTION_KEY` are both stolen. Use a per-deployment salt. |
| Git health `str(e)` | Authenticated; still an information leak. |

### 4.4 Categories checked with no confirmed defect

| Category | Result |
|----------|--------|
| SQL injection | ORM/`select()`; `text()` allow-listed; bound parameters. |
| Command injection | Git subprocess uses argument lists, no `shell=True`. |
| Path traversal | Git paths sanitized (`services/git/paths.py`); file reads `realpath` + root check. |
| JWT algorithm confusion | HS256 pinned (`core/auth.py:32–36`); OIDC uses RS*. |
| Password hashing | `pwdlib.PasswordHash.recommended()` in `auth_service.py`. |
| Pickle / `eval` / `exec` / unsafe YAML | `yaml.safe_load` only. |
| Jinja SSTI | `SandboxedEnvironment` in workflow render and templates. |
| Mass assignment | Pydantic models; updates use `exclude_unset`. |
| Workflow JSON | Step types validated against `STEP_REGISTRY` at execution. |
| Credential list API | Secrets not returned; reveal requires `credentials:reveal`; private creds are owner-scoped. |
| Private workflow IDOR | Enforced on workflow/run read/update/delete. |
| Login user enumeration | Dummy hash when user is missing (`auth_service.py`). |
| Router 5xx leaks | Regression script green. |

---

## 5. Large files to refactor

**473** non-test Python files. **51** are ≥300 lines, **13** ≥500, **5** ≥700.

### 5.1 Highest priority (mixed responsibilities)

| Path | Lines | Why split |
|------|------:|-----------|
| `hatchet/workflows/workflow_run.py` | 939 | Durable workflow: prepare, step loop, fan-out dispatch, debug pause, child aggregation, finalize. Split into `prepare`, `fan_out`, `debug_pause`, `finalize`. |
| `services/execution/step_runner.py` | 894 | Topological execution + funnel graph rewrite + fan-out protocol + artifact/session wiring. Extract funnel resolution and fan-out types; keep the runner as a coordinator. |
| `services/git/file_service.py` | 763 | List, search, history, YAML, CSV, HTTP errors in one class. Split by operation; stop raising `HTTPException`. |
| `services/nautobot/devices/interface_workflow.py` | 755 | Interface + IP create/update in one procedural module. Split create / update / IP assignment. |
| `services/nautobot/devices/update.py` | 707 | Cohesive domain, too long. Extract field-mapping and primary-IP helpers. |
| `services/git/debug_service.py` | 683 | Dev-only diagnostic junk drawer. Acceptable behind `ENABLE_DEV_TOOLS`; still split by diagnostic type if it keeps growing. |
| `routers/sources/ise/ops.py` | 570 | Fat router. Move to `services/ise/` and leave HTTP wiring. |
| `services/git/service.py` | 557 | Facade over clone/commit/push/pull. Borderline; already delegates to auth/env/paths. |
| `routers/sources/nautobot/ops.py` | 551 | Fat router. Delegate to existing source/query services. |

### 5.2 Large workflow executors (inherent complexity)

Network/ISE/Nautobot steps are long because they mix validation, vendor APIs, and result shaping. They are not “dead” god objects, but several would benefit from shared helpers:

| Path | Lines |
|------|------:|
| `workflow_steps/configure_replace_config/executor.py` | 685 |
| `workflow_steps/deploy_rendered_template/executor.py` | 553 |
| `workflow_steps/compare_pyats_snapshot/executor.py` | 519 |
| `workflow_steps/compare_data/executor.py` | 513 |
| `workflow_steps/get_ise_tacacs_key/executor.py` | 490 |
| `workflow_steps/add_to_ise/executor.py` | 484 |
| `workflow_steps/store_artifact/executor.py` | 439 |
| `workflow_steps/upload_config/executor.py` | 415 |
| `workflow_steps/update_nautobot_device/executor.py` | 402 |

Suggested split for the two largest: precheck / mutate / postcheck / parse, as sibling modules under the step package. Do **not** put that logic into `step_registry.py`.

### 5.3 Large files that are acceptable as-is

| Path | Lines | Reason |
|------|------:|--------|
| `services/nautobot/devices/common.py` | 443 | Documented facade, not a God object. |
| `services/cache/redis_cache_service.py` | 465 | Single responsibility. |
| `migrations/auto_schema.py` | 463 | Schema-diff engine used by manager + CLI. |
| `services/sources/nautobot/query_service.py` | 439 | Focused cache-first query service. |
| `scripts/database/sync.py` | 360 | CLI entry point. |

---

## 6. Dead code

### 6.1 High confidence — unused wrappers

| Item | Evidence |
|------|----------|
| `service_factory.build_git_repository_service()` | Defined at `service_factory.py:192–195`. Zero call sites. `GitRepositoryService()` is constructed directly in `services/git/shared_utils.py`. |
| `dependencies.get_git_service()` | Defined at `dependencies.py:72–73`. Never used as `Depends(...)`. Callers use `service_factory.build_git_service()`. |

Safe to delete both.

### 6.2 Medium confidence — overlapping implementations (live, but duplicated)

| Overlap | Locations | Verdict |
|---------|-----------|---------|
| Filter-tree → operations | `utils/inventory_converter.tree_to_operations` vs `_filter_tree_to_operations` in `workflow_steps/get_nautobot_devices/executor.py:26–59` | Consolidate on the shared utility. |
| Nautobot custom-field REST | `services/nautobot/metadata_service.py` (`NautobotMetadataService`) vs `services/sources/nautobot/metadata_service.py` (`NautobotSourceMetadataService`) | Same `extras/custom-fields/` endpoint, different shaping/caching. Merge candidate. |

These are **not** dead; they are duplicate live paths.

### 6.3 Not dead (checked)

| Category | Result |
|----------|--------|
| Unreferenced modules | None among application packages. `workflow_steps/*`, `hatchet/workflows/*`, and plugin registry load dynamically. |
| Unregistered routers | All 47 router modules are included from `main.py` or package aggregators. |
| Unused repositories | All domain repositories are referenced, including inventory, notification, schedule. |
| Unused models | All `core/models` tables are exported and used. |
| Inventory domain | Active: model, repository, `InventoryService`, Nautobot CRUD/ops, workflow steps. |
| `workflow_steps/funnel/` | Canvas-only node; resolved in `step_runner._resolve_funnels`, not executed. |
| Commented-out blocks | None of significant size. |
| Always-false flags | `RUN_RETENTION_ENABLED`, migration flags, `INSTALL_CERTIFICATE_FILES`, `ALLOW_LOOPBACK_SOURCE_URLS` default false but are env-toggleable and referenced. |

### 6.4 Leftover scripts

Production / CI:

- `scripts/check_asyncio_run.py`, `check_http_500_leaks.py`, `check_router_repositories.py`, `check_text_sql.py` — regression guards (keep).
- `scripts/run_worker_dev.py` — Hatchet hot-reload (keep).
- `scripts/purge_retention.py`, `scripts/database/sync.py` — ops (keep).
- `scripts/parse_config.py`, `scripts/parse_config_keys.py` — local debug utilities (keep if used).

Leftover **manual ISE sandbox tests** (hardcoded `10.10.20.77`, `admin` / `C1sco12345!`):

- `scripts/ise_test.py`
- `scripts/ise_test_delete_device.py`
- `scripts/ise_test_update_tacacs.py`
- `scripts/ise_test_devices_by_ndg.py`
- `scripts/ise_test_ndg_add.py`
- `scripts/ise_test_ndg_update.py`
- `scripts/ise_test_ndg_delete.py`
- `scripts/ise_test_ndg_list.py`
- `scripts/ise_show_all_devices.py`

These are not imported by the app. They are lab leftovers. Default sandbox credentials in-tree are a hygiene issue even if they are public Cisco DevNet defaults.

### 6.5 Stale comments

Celery comments in `hatchet/workflows/cache_devices.py` and `utils/inventory_converter.py`. Git compare router is already removed (`routers/git/main.py` notes this).

---

## 7. Documentation drift (`CLAUDE.md` vs code)

`CLAUDE.md` should be updated so future work is measured against the real system:

| Claim in `CLAUDE.md` | Actual |
|----------------------|--------|
| “14 tables (9 domain + 5 RBAC)” | **17 tables**: 12 domain (`users`, `credentials`, `git_repositories`, `inventories`, `settings`, `templates`, `workflows`, `workflow_runs`, `workflow_step_results`, `notifications`, `workflow_schedules`, `user_preferences`) + 5 RBAC. |
| Key models list omits notifications, schedules, user preferences | Those modules exist and are exported. |
| “Never call `text()` from … or Celery tasks” | There is no Celery. Say Hatchet workers. |
| “Python 3.12+” | Project venv is Python 3.14 (`CLAUDE.md` development workflow section). |
| “Python/Celery projects” under Python Conventions | Hatchet, not Celery. |

---

## 8. Recommended priority

### P1 — security

1. Enable Git SSH host-key checking (persisted `known_hosts`).
2. Apply outbound IP policy to SSH git remotes.
3. Guard admin-role assignment / self-elevation.
4. Refuse `ENABLE_DEV_TOOLS` outside `ENV=development`; never relax OIDC redirects.

### P2 — architecture (standards)

1. Stop raising `HTTPException` from services; map domain errors in routers; use `raise_internal_server_error` for all 5xx.
2. Extract orchestration from `routers/git/operations.py`, `routers/netmiko.py`, `routers/sources/ise/ops.py`, `routers/sources/nautobot/ops.py`.
3. Add RBAC to dashboard endpoints (or document the exception).
4. Move step `get_config()` loading into the plugin registry.

### P3 — maintainability

1. Split `hatchet/workflows/workflow_run.py` and `services/execution/step_runner.py`.
2. Split `services/git/file_service.py`.
3. Delete unused `build_git_repository_service` / `get_git_service`.
4. Consolidate inventory tree conversion and Nautobot metadata services.
5. Inject request-scoped `Session` into Git repository CRUD.
6. Relocate or clearly mark ISE sandbox scripts; refresh `CLAUDE.md` table/Celery/Python notes.
7. Require Redis authentication outside development; review login limiter fail-soft behaviour.

---

## 9. What is working well

Keep these; they are the right defaults for new code:

- Layered domain services for workflows, runs, users, credentials, templates, RBAC.
- Regression scripts under `backend/scripts/check_*.py`.
- Production secret guards in `core/production_guards.py`.
- Outbound HTTP URL policy (`core/safe_urls.py`) and OIDC redirect allowlist (`core/oidc_redirect.py`).
- Plugin/step registry as a dispatch table with executors isolated under `workflow_steps/`.
- Nautobot Resolver/Manager + `DeviceCommonService` facade (documented exception to the repository pattern).
- Sandboxed Jinja, `yaml.safe_load`, HS256-only JWT, pwdlib password hashing, no CORS.
- Private workflow/credential IDOR checks and secret redaction for known sealed paths.
