# Backend analysis — 13 August 2026

Review of `backend/` against `CLAUDE.md`, file-size / god-object maintainability, security, dead code, and production-readiness. The app is not in production yet; findings are ordered so a first release can be planned against them.

**Scope:** FastAPI / Python under `backend/` (525 files, ~420 production). Frontend security already recorded in `doc/GROK-20260813-ANALYSIS.md` is not re-litigated here, except where the backend contract still forces secrets into the browser or leaves a hole the SPA cannot close. Accepted server-side risks already written down in `doc/SECURITY-NOTES.md` are verified, not re-argued.

**Method:** layer-pattern audit, router registration vs `main.py`, `wc -l` ranking, AST-style class/method inspection of the largest modules, grep for disallowed patterns (`sqlalchemy.text()`, `HTTPException` 5xx leaks, `shell=True`, `pickle`/`eval`/`yaml.load`, `verify_ssl=False`, f-string logging), registry alignment (`registry.yaml` vs `STEP_REGISTRY`), and targeted reads of auth, settings, sources, execution, and git.

All four regression guards were run and **passed**:

| Script | Enforces |
|---|---|
| `scripts/check_router_repositories.py` | No `repositories` imports under `routers/` |
| `scripts/check_http_500_leaks.py` | No leaky 5xx `HTTPException(detail=…)` in routers |
| `scripts/check_text_sql.py` | No forbidden `text()` outside the allow-list |
| `scripts/check_asyncio_run.py` | No `asyncio.run()` in routers |

---

## 1. Executive summary

The backend **largely follows** the architecture in `CLAUDE.md`: Model → Repository → Service → Router, PostgreSQL + SQLAlchemy, JWT + per-request RBAC, Hatchet for durable runs, Redis for cache / OIDC state / login rate limits, Pydantic on most endpoints, and a registry-driven workflow-step dispatch. There is no CORS middleware (proxy-only is intact). There is no `pickle` / `eval` / `exec` / `yaml.load` / `shell=True` in runtime code. Jinja rendering is sandboxed. Artifact and git file paths reject `..`. Nautobot HTTP URLs go through `validate_outbound_http_url`. Settings GET now redacts Nautobot/Git tokens.

It is **not yet production-ready**. No unauthenticated admin path was found, but several issues should be treated as release blockers:

1. **Nautobot and Git API tokens are stored plaintext in PostgreSQL** (`settings.value`). ISE and pyATS already use the encrypted `credentials` table. A DB backup or stolen DB password is a full token dump. The ISE service even documents this gap.
2. **`ENV` defaults to `development`.** Production guards (`SECRET_KEY`, `INITIAL_PASSWORD`, OpenAPI docs off) only fire when `ENV` is *not* `development`. A forgotten env var ships default `admin`/`admin` and `/docs`.
3. **Git `clone` accepts arbitrary URL schemes** (`file://`, internal HTTP, SSH) with no allow-list. Authenticated users can make the server fetch from places it should not.
4. **OIDC `redirect_uri` is client-supplied and not bound to Redis state.** CSRF `state` itself is one-time and checked; the redirect is not.
5. **Break-glass HTTP surfaces stay live in a production process** unless you remember extra flags: git debug write/push, schema migrate, RBAC wipe-and-reseed, system CA install. OIDC test/debug *is* gated by `ENABLE_DEV_TOOLS`. The others are RBAC-only.

File size is healthier than the frontend. **No production file exceeds 1,000 lines.** Two files are large enough to keep accumulating bugs: `hatchet/workflows/workflow_run.py` (940) and `services/execution/step_runner.py` (824, 23 methods). `DeviceCommonService` looks large (443 lines, 43 methods) but is still a thin facade — it has **not** become a god object.

Overall CLAUDE.md grade: **solid skeleton, uneven enforcement**. Layering, RBAC, Nautobot resolver/manager split, and step-registry dispatch are in good shape. Git persistence, service-layer `HTTPException`, token-at-rest, and a few fat routers slip.

---

## 2. What is already in good shape

| Area | Evidence |
|---|---|
| Layering (routers) | Routers do not import repositories. `check_router_repositories.py` is clean. |
| Raw SQL | No runtime `sqlalchemy.text()` outside the documented allow-list. No f-string SQL. |
| 5xx in routers | Widespread `raise_internal_server_error`. Guard script allow-list is empty. |
| CORS | No `CORSMiddleware`. Frontend must use the Next.js proxy. |
| Auth on routes | Protected routers use `get_current_user` / `require_permission`. Public: `/health`, `/auth/login`, `/auth/refresh`, OIDC login/callback/providers. |
| Inactive users | `get_current_user` and permission deps reject `is_active=False`. |
| Login lockout | Redis sliding window, 5 attempts / 60s (`LoginRateLimiter`). 429 body is generic. |
| OIDC CSRF state | One-time Redis key, provider-id prefix check, 10-minute TTL. |
| Settings GET tokens | `_redact_source_token` blanks `token` and adds `token_configured` for Nautobot/Git. |
| Source lookup by id | Custom fields and most Nautobot ops take `source_id`; server loads the token (`nautobot_credentials_from_source_id`). |
| Nautobot HTTP SSRF | `validate_outbound_http_url` on REST/GraphQL (scheme, no userinfo, no link-local/metadata; RFC1918 allowed on purpose). |
| ISE/pyATS persist | URL validated; passwords live in encrypted `credentials`. |
| Path traversal | Filesystem artifact sink and git `realpath`+repo-root checks reject `..` / absolute paths. Cert upload filenames are sanitized. |
| Jinja SSTI | `SandboxedEnvironment` in `workflow_steps/common/jinja_render.py`. |
| YAML | `yaml.safe_load` only. |
| Logging | No `logger.*(f"…")`. |
| Docs in prod | `/docs` and `/redoc` off unless `DOCS_ENABLED` or `ENV=development`. |
| Default secrets | `SECRET_KEY` and `INITIAL_PASSWORD` raise at startup when `ENV != development`. |
| Step registry | 39 executable plugins in `registry.yaml` = 39 `STEP_REGISTRY` keys. `label` / `background` correctly non-executable. |
| Nautobot architecture | Client + resolvers + managers + `DeviceCommonService` facade. Not a repository. |
| Credentials API | List/detail return `has_password` flags, not SSH/TACACS secrets. |
| OpenAPI version | App version is `0.1.0` — honest for a first release. |
| Unit tests | 104 `tests/unit/test_*.py` files. Execution, ISE, credentials, OIDC, artifacts, and most step executors are covered. |

---

## 3. File size

Threshold used (same as the frontend analysis): **300+ lines = large**, **500+ = should split**, **800+ = blocking for further feature work in that file**.

### 3.1 Counts

| Threshold | All files | Production (excl. `tests/`) | Tests |
|-----------|-----------|-----------------------------|-------|
| **> 300** | 64 | 50 | 14 |
| **> 500** | 16 | 12 | 4 |
| **> 800** | 2 | 2 | 0 |
| **> 1000** | 0 | 0 | 0 |

`core/` is healthy (largest: `config.py` 178, `auth.py` 177). `services/auth/` and `services/settings/` stay under 315 lines.

### 3.2 Ranked production files > 500 lines

| Lines | File | Why it is large | Split recommendation |
|------:|---|---|---|
| 940 | `hatchet/workflows/workflow_run.py` | Durable Hatchet workflow: phase-1 run, fan-out, child dispatch, batch approval, aggregation. ~20 module-level async functions. Longest: `_aggregate_and_persist` (~109 lines). | Package `hatchet/workflows/workflow_run/` — `_dispatch_*`, `_approval_*`, `_aggregate_*`. Keep the `@workflow.task` entry points thin. |
| 824 | `services/execution/step_runner.py` | `StepRunner` (23 methods): graph plan, sequential run, fan-out/join, device sessions, persistence, secret redaction. | `GraphPlanner`, `StepExecutor`, `OutcomePersister`; keep a thin `StepRunner` facade. |
| 763 | `services/git/file_service.py` | Tree walk, search, history, YAML. Fat methods, not mixed domains. | `git/file_tree.py` + `git/file_content.py`. |
| 755 | `services/nautobot/devices/interface_workflow.py` | Interface + IP lifecycle. Single domain, long private methods. | Extract IP assignment vs interface CRUD. |
| 735 | `services/git/service.py` | GitPython clone/pull/push/commit + result dataclasses. | Move result types to `git/types.py`. Already split from `operations.py` / `connection.py`. |
| 715 | `services/nautobot/devices/update.py` | Device patch + unfinished `create_if_missing`. | Split resolve vs apply. Remove or implement the TODO. |
| 683 | `services/git/debug_service.py` | Dev diagnostics; `test_write` is 91 lines. | Fine as a diagnostic module; gate the HTTP surface (see §5). |
| 553 | `workflow_steps/deploy_rendered_template/executor.py` | Per-device Netmiko deploy + artifact store. | Helpers inside the step package. |
| 551 | `routers/sources/nautobot/ops.py` | 16 endpoints; some inventory conversion inline. | `preview.py` / `resolve.py` / `fields.py` under the same package. |
| 550 | `routers/sources/ise/ops.py` | 18 ISE device/group endpoints. | Device vs group sub-routers. |
| 513 | `workflow_steps/compare_data/executor.py` | Multi-device text compare. | Extract compare logic. |
| 506 | `workflow_steps/compare_pyats_snapshot/executor.py` | Snapshot diff. | Extract diff builder. |

Workflow-step executors in the 300–500 band (`get_ise_tacacs_key`, `add_to_ise`, `store_artifact`, `run_command`, …) are **one responsibility each**. Size comes from the per-device fan-out pattern, not from god objects. Prefer shared helpers in `workflow_steps/common/` over splitting every executor.

### 3.3 Why the two 800+ files matter for a first release

`StepRunner` is the product’s execution kernel. Every new step, fan-out rule, or session-pool change lands in the same 23-method class. That is how persistence, redaction, and graph-planning bugs accumulate.

`workflow_run.py` is the Hatchet counterpart: durable waits, child workflows, approval gates. It is a procedural god-module (no dominant class) with the same maintenance risk.

Neither needs to be split **before** first traffic if you freeze fan-out behaviour. They should be split **before** the next wave of execution features.

---

## 4. God objects

CLAUDE.md: never create monolithic God Object services. `DeviceCommonService` is documented as a facade.

| Component | Verdict | Severity |
|---|---|---|
| `DeviceCommonService` (`devices/common.py`, 443 lines, 43 methods) | **Healthy facade.** Almost every method is a 1–3 line delegate to a resolver/manager. No GraphQL, no HTTP, no DB. Has **not** drifted. | None — do not split. |
| `NautobotService` (`client.py`, ~199 lines) | HTTP client only. | None |
| `service_factory.py` (233 lines) | DI factory; git-heavy because git is fragmented, not because the factory is a god object. | None |
| `StepRunner` (824 lines, 23 methods) | **Primary god object.** Graph + execute + persist + sessions + redaction. | High |
| `workflow_run.py` (940 lines) | **God module** (procedural). Hatchet + DB + approval + fan-out. | High |
| `InterfaceManagerService` / `DeviceUpdateService` | Deep but single-domain. | Low |
| `GitFileService` | Fat methods, one domain. | Low |
| `nautobot/ops.py`, `ise/ops.py` | Fat routers, not god objects. | Medium |
| Step executors | Large, single-purpose. | Low (systemic) |

---

## 5. CLAUDE.md compliance

### 5.1 Scorecard

| Rule | Status |
|---|---|
| SQLAlchemy models in `core/models/{domain}.py`, exported from `__init__.py` | **Pass** — 11 model files, all exported including `WorkflowSchedule`. |
| Pydantic in `models/{domain}.py` | **Partial** — 27 modules exist; several git/nautobot ops endpoints return untyped `dict` (no `response_model`). |
| Repository in `repositories/{domain}_repository.py` using `BaseRepository` | **Partial** — 10 domain repos exist. **Only** `GitRepositoryRepository` subclasses `BaseRepository`. Others inject a request-scoped `Session` (the better pattern). |
| Service in `services/{domain}/{domain}_service.py` | **Partial** — core domains match. Git is ~12 modules; Nautobot is client/resolver/manager (correct for an external API). |
| Router registered in `main.py` | **Pass** — 28 router groups; no orphan routers. |
| Thin routers — no business logic, no repository calls | **Partial** — no repository imports. Orchestration still lives in `routers/sources/nautobot/ops.py` (`convert_saved_inventory_to_operations`) and `routers/git/operations.py` (sync status lifecycle). |
| Never bypass repository for local DB | **Partial** — most services use repos. Git uses `BaseRepository._db_session()` (own connections) plus a module singleton `git_repo_manager` in `services/git/shared_utils.py`. |
| `sqlalchemy.text()` only in repositories / allow-list | **Pass** — guard clean. Runtime repos use SQLAlchemy `select()` / ORM. |
| Never compose SQL via f-strings | **Pass** |
| 5xx use `raise_internal_server_error`, never raw exception text | **Partial** — routers pass the guard. `WorkflowService` raises `HTTPException(500, detail="Workflow created but could not be retrieved")` (sanitized text, no `error_id`) and re-raises bare `Exception` after logging. FastAPI’s default handler will *not* put that exception text in the body when debug is off; the `{message, error_id}` contract is still skipped. `check_http_500_leaks.py` does not scan `services/`. |
| Workflow steps: 5-file pattern, `STEP_REGISTRY` only | **Partial** — registry aligned (39/39). `StepRunner` dispatches via the registry. Production leaks: `services/artifacts/sinks/git_sink.py` and `services/workflow_context/attribute_path.py` import `workflow_steps.common.device_template`. |
| Nautobot: resolver / manager / facade, not repository | **Pass** |
| Permissions via `require_permission` | **Partial** — widespread. Intentional public: login, refresh, OIDC login/callback/providers, `/health`. Gap: `GET /general/settings` is authenticated but has no `general_settings:read`. |
| Pydantic validation on endpoints | **Partial** — CRUD/workflow mostly typed. `routers/git/files.py` has no `response_model`. |
| No f-string in logging | **Pass** |
| Feature-based organization | **Partial** — sources, nautobot, execution are grouped. Git is split but shares a singleton. |

**Overall:** ~6 Pass, ~10 Partial, 0 hard Fail on the automated checks. The Partials that matter for a first release are git session management, service-layer 500 contract, token-at-rest, and fat source routers.

### 5.2 Layer pattern — what actually exists

```
core/models/     11 files, 15 tables   → exported from __init__.py
models/          27 Pydantic modules
repositories/    10 domain repos + BaseRepository + plugin_repository
services/        135 files, domain packages
routers/         42 files, registered in main.py
workflow_steps/  39 executors + label/background
```

This is the intended shape. Drift is in **how strictly** each domain uses it, not in missing layers.

### 5.3 Table count vs CLAUDE.md

CLAUDE.md says **14 tables (9 domain + 5 RBAC)**. The code has **15 tables (10 domain + 5 RBAC)**. The missing entry is `workflow_schedules` (`core/models/schedules.py`).

### 5.4 `BaseRepository` vs injected `Session`

The documented standard is “use `BaseRepository`”. The *better* pattern in this codebase is the one most repos already use: construct with a request-scoped `Session` from `get_db()`. `BaseRepository` opens and commits its own sessions when `db` is omitted — that fights FastAPI’s transaction boundary.

Git is the odd one out: it inherits `BaseRepository` *and* uses the session-owning path. Align git with the injected-session repos; treat `BaseRepository` as optional infrastructure, or update CLAUDE.md to say “injected `Session` + repository class” instead of requiring the base class.

### 5.5 Workflow-step boundary leaks

CLAUDE.md: external code must never import `workflow_steps` packages; only `StepRunner` calls executors. `step_registry.py` importing executors is the intended dispatch table.

Violations (move the helpers to `services/workflow_context/` or `services/artifacts/`):

- `services/artifacts/sinks/git_sink.py` → `workflow_steps.common.device_template.sanitize_relative_path`
- `services/workflow_context/attribute_path.py` → `workflow_steps.common.device_template.build_template_context`

### 5.6 CLAUDE.md drift (docs, not code defects)

| Topic | CLAUDE.md | Code |
|---|---|---|
| Python | “3.12+” and also “venv is Python 3.14” | Project venv is **3.14.4** |
| Tables | 14 (9 + 5) | **15 (10 + 5)** — `workflow_schedules` |
| Orchestration | Hatchet in product direction; **Celery** still named in the raw-SQL rule and “Python conventions” | No Celery imports, no `celery` in `requirements.txt` |
| `REFACTORING_RAW_SQL.md` | Referenced from CLAUDE.md and `check_text_sql.py` | **File does not exist.** Closest: `doc/refactoring/GROK-20260813-REFACTORING.md` (frontend). |
| Step `__init__.py` | “empty” | Present in all step packages (harmless) |

---

## 6. Security findings

Severity: **P0** = fix before first production traffic; **P1** = fix in the first production hardening sprint (treat as release blockers for an external or multi-tenant deploy); **P2** = backlog / defence in depth.

### 6.1 P0 — none confirmed in the backend HTTP surface

No unauthenticated admin routes, no open CORS, no router-layer 5xx exception leaks, no `pickle`/`eval`/`exec`/`yaml.load`/`shell=True`, no JWT in `localStorage` (that is a frontend concern). Login returns a token in JSON because the Next.js auth routes set the HttpOnly cookie — that is the intended API contract.

The frontend analysis’s P0 “tokens on GET query strings” is **already closed on the backend** for custom fields and the current Nautobot ops models (`NautobotSourceRef.source_id`). Dead Pydantic models in `models/plugins.py` still declare `nautobot_token` (see §7) but no live router uses them.

Remaining secret-handling work is **at rest** and **in Git clone URLs**, not “token in the query string”.

### 6.2 P1 — Nautobot / Git tokens plaintext in PostgreSQL

`SettingsService._redact_source_token` blanks tokens on **read**. The row in `settings.value` still holds the raw token. Confirmed by `tests/unit/test_settings_token_redaction.py` (the test asserts the DB keeps the token). ISE documents the inconsistency:

```1:6:backend/services/ise/source_config_service.py
"""Cisco ISE source configuration: pairs a settings entry with an encrypted credential.
...
the username/password live in the encrypted ``credentials`` table (source="ise")
so the password is never stored in plaintext, unlike the Nautobot token today.
```

**Impact:** DB dump, stolen `DATABASE_PASSWORD`, or a future SQL bug exposes every Nautobot and Git token.

**Fix:** Store those tokens in the encrypted `credentials` table (same as ISE/pyATS), or encrypt the token field with `EncryptionService` and migrate existing rows. Keep GET redaction either way.

### 6.3 P1 — `ENV` defaults to `development`

```61:63:backend/core/config.py
        self.environment = environ.get("ENV", "development")
        ...
        self.docs_enabled = self._get_bool("DOCS_ENABLED", self.environment == "development")
```

Production checks (`SECRET_KEY` must not be the default, `INITIAL_PASSWORD` must not be `admin`) only run when `environment != "development"`. `docker/docker-compose.yml` and both `.env.example` files set `ENV=development`. `Dockerfile.all-in-one` sets `NODE_ENV=production` but **not** `ENV=production` (the README tells you to pass `-e ENV=production`).

**Impact:** A deploy that forgets `ENV=production` starts with `admin`/`admin`, the default JWT signing key, and `/docs` enabled.

**Fix:** Fail startup if `ENV` is unset in a container/image; or default `docs_enabled` to false and require an explicit `ENV=development` to allow default secrets. Document a one-page production env checklist (see §9).

### 6.4 P1 — Git clone has no URL scheme / SSRF policy

Nautobot/ISE HTTP URLs are validated. Git is not.

`services/sources/git/git_source_service.py` (test-connection) and `services/git/connection.py` pass the user URL straight to `git clone`. Schemes such as `file://`, `ssh://`, and internal HTTP git are accepted. Failed clones return redacted stderr to the client — still useful for host/path reconnaissance.

**Fix:** Allow-list `https` and `ssh` (and `git` if you truly need it). Reject `file://` and bare paths. Optionally run HTTP(S) remotes through `validate_outbound_http_url`. Sanitize client-facing clone errors.

Git credentials in process argv remain an **accepted risk** (`doc/SECURITY-NOTES.md`). The scheme allow-list is new work, not a re-litigation of argv.

### 6.5 P1 — OIDC `redirect_uri` not allow-listed or bound to state

Backend CSRF state is in good shape (Redis, one-time, provider prefix). `redirect_uri` is not stored with that state:

```75:81:backend/routers/oidc.py
async def initiate_login(
    provider_id: str,
    redirect_uri: str,
    ...
```

```133:133:backend/routers/oidc.py
    cache.set(f"oidc-state:{state_with_provider}", "1", ttl_seconds=OIDC_STATE_TTL_SECONDS)
```

Callback uses `body.redirect_uri` as given. Combined with a permissive IdP client (wildcard or multiple redirect URIs), this is authorization-code interception / open-redirect phishing.

**Fix:** Allow-list frontend origins from env. Store `{redirect_uri}` (or a hash) in Redis with state. Reject the callback if it does not match. This is independent of the frontend `sessionStorage` fail-closed fix in the frontend analysis.

### 6.6 P1 — Netmiko preview is an SSH pivot

`POST /netmiko/run-commands` and `POST /netmiko/get-configs` take `payload.host` from the client. Permission is `netmiko:execute`. There is no inventory allow-list.

**Impact:** Anyone with that permission can SSH from the backend into RFC1918 / metadata / lab hosts using stored credentials.

**Fix:** Resolve hosts from inventory (or an explicit allow-list), or document this as an accepted internal-network tool in `SECURITY-NOTES.md` the same way host-key checking already is. Do not ship it undocumented to a network you do not fully trust.

### 6.7 P1 — Break-glass tools: mixed gating

| Surface | Gating today | Risk |
|---|---|---|
| `POST /auth/oidc/{id}/test-login`, `GET /auth/oidc/debug` | `ENABLE_DEV_TOOLS` + `system.oidc:read` (404 when off) | Correct. Keep off in prod. Debug returns `client_id`, discovery URLs, `config_path`. |
| `POST /git-repositories/{id}/debug/{read,write,delete,push}` | `git.debug:execute` only | **Writes and pushes** in real repos. `SECURITY-NOTES.md` accepted the RBAC gate; for a first *product* release, also hide behind `ENABLE_DEV_TOOLS` or omit the router. |
| `POST /system/schema/migrate` | `system.database:write` | Live schema migrate over HTTP. |
| `POST /system/rbac/seed?remove_existing=true` | `system.rbac:write` | Wipes RBAC. |
| `POST /certificates/...` `add_to_system` | `system.certificates:write` | Copies a CA into `/usr/local/share/ca-certificates` and runs `update-ca-certificates`. Startup install is gated by `INSTALL_CERTIFICATE_FILES` (default false); **the HTTP path is not.** |

RBAC is necessary and correctly applied. It is not sufficient if the day-one admin role is broad or a session is stolen.

**Fix for v1:** `ENABLE_DEV_TOOLS` (or `ENV=production`) must disable git debug, schema migrate, RBAC wipe, and system-CA install — or those routes must not be registered. Keep OIDC test as-is (already gated).

### 6.8 P1 — Credential encryption key may be the JWT secret

```26:31:backend/services/credentials/credentials_service.py
        secret = resolve_credential_secret(
            settings.credential_encryption_key or settings.secret_key
        )
```

`CREDENTIAL_ENCRYPTION_KEY` is optional. Production only requires `SECRET_KEY` and `INITIAL_PASSWORD`. The Fernet key is derived with a **hardcoded salt** (`auxilium-credential-encryption-v1`) so the same secret always yields the same key (needed to decrypt). That means a leaked JWT signing key also decrypts every stored SSH/ISE/pyATS secret.

**Fix:** Require a distinct `CREDENTIAL_ENCRYPTION_KEY` when `ENV != development`.

### 6.9 P2 — Hardening

| Finding | Evidence | Fix |
|---|---|---|
| **No JWT revocation** | No `jti` / denylist. Logout is cookie-delete on the frontend; OIDC logout only builds an IdP end-session URL. Stolen Bearer works until `ACCESS_TOKEN_EXPIRE_MINUTES` (default **60**). | Document the TTL. Optional Redis denylist if sessions last hours. |
| **Refresh accepts expired access tokens** | `POST /auth/refresh` — by design, signature still checked. | Fine if the cookie never reaches JS. Keep the TTL short. |
| **`GET /general/settings` has no read permission** | Router-level `get_current_user` only. PUT correctly requires `general_settings:write`. | Add `require_permission("general_settings", "read")`. Export path is low-sensitivity; still inconsistent. |
| **Login rate limit fail-open on Redis** | In-process fallback per worker. | Monitor Redis. Optional fail-closed flag. |
| **`X-Forwarded-For` trust** | `routers/auth.py` uses `TRUSTED_PROXY_IPS`. Empty default. | Keep empty unless behind a known proxy. Mis-set list = rate-limit bypass. |
| **Token redaction is key-prefix specific** | Only `source.nautobot.*` / `source.git.*`. A token stuffed under `app.misc` is returned. | Redact any setting value whose keys include `token` / `password` / `secret`, or ban those keys outside the credential store. |
| **pyATS `verify_ssl` defaults False** | `services/pyats/credentials.py` | Default `True`; document the override. Same class as Nautobot/ISE accepted risk. |
| **Git SSH `StrictHostKeyChecking=no`** | `services/git/auth.py`, `connection.py` | Same accepted-risk class as Netmiko host keys. Add to `SECURITY-NOTES.md`. |
| **Git test returns stderr** | After redaction, still path/host hints. | Generic “clone failed” to the client; keep detail in logs. |
| **Inventory health_check embeds `str(e)`** | `persistence_service.py` | Sanitize if that string is ever returned over HTTP. |
| **No global exception handler** | Unhandled errors become FastAPI’s generic 500 (good). No `error_id` for correlation. | Optional handler that logs an id and returns `{message, error_id}` for all unhandled 500s. |
| **`/health` is shallow** | `{"status": "ok"}` — no DB, no Redis, no Hatchet. | Add `/health/ready` that checks Postgres (`SELECT 1`) and Redis. Keep `/health` cheap for the load balancer. |
| **Default DB password `postgres`** | Not rejected in production (only JWT/admin password are). | Require `DATABASE_PASSWORD` when `ENV != development`. |
| **JWT algorithm HS256, no `aud`/`iss`** | Fine for a first-party API. | Add `iss`/`aud` if tokens are ever shared. |

### 6.10 Verified still present (`doc/SECURITY-NOTES.md`)

Do not re-investigate these without new evidence. They are accepted for a managed internal network:

| Item | Still true? |
|---|---|
| `verify_ssl=False` on Nautobot/ISE, WARNING per request | Yes |
| Netmiko: no SSH host-key verification | Yes |
| Git credentials in process argv; stdout/stderr redacted | Yes |
| pyATS shim over plain HTTP on the internal Docker network | Yes |
| Git debug write/push behind `git.debug:execute` | Yes — see §6.7 for the product decision |

### 6.11 What we did *not* find

- CORS wide open
- Router → repository imports
- `sqlalchemy.text()` in services/routers/tasks
- `str(e)` in router 5xx `HTTPException` detail
- `shell=True`, `pickle`, `eval`, `exec`, unsafe `yaml.load`
- f-string logging
- Path traversal on artifact export or git file read
- Jinja unsandboxed
- Production SQLite
- Celery runtime
- Orphan routers
- Settings GET returning Nautobot/Git tokens (redaction is live)
- Live routes taking `nautobot_token` as a query parameter (moved to `source_id`)
- JWT or passwords stored by the backend in a browser-readable way

---

## 7. Dead code and leftovers

The backend is **mostly clean**. Celery is gone from runtime. Routers and workflow steps are aligned. What remains is leftover comments, one dead function, one unfinished feature, dead Pydantic models, and dangerous one-off scripts.

### 7.1 Dead or unfinished application code

| Item | Path | Action |
|---|---|---|
| `get_cached_commits()` | `routers/git/operations.py` | **Dead.** Marked DEPRECATED, never called. Delete. |
| `DeviceImportService` / `create_if_missing` | `services/nautobot/devices/update.py:241-243` | **Phantom type** — class does not exist. `create_if_missing=True` raises `ValueError`. Implement or remove the flag and the TODO. |
| `DeviceSelectionPreviewRequest`, `FieldValuesRequest` (token fields) | `models/plugins.py:109-147` | **Dead models.** Live types are `NautobotSourceRef` / `FieldValuesRequest` in `models/sources_nautobot.py`. Delete the token-bearing copies so they cannot be wired up again. |
| `retention_policy` on store-artifact | `workflow_steps/store_artifact/config.py`, `registry.yaml` | Config exists; executor ignores it (“reserved”). Implement or drop from the schema. |
| Celery wording | `utils/inventory_converter.py` docstring, `hatchet/workflows/cache_devices.py` comment, CLAUDE.md, `.gitignore` `celerybeat-*` | Comments only. The Hatchet cron in `cache_devices.py` is live. |

### 7.2 Scripts

| Script | Role | Production-safe? |
|---|---|---|
| `check_asyncio_run.py`, `check_http_500_leaks.py`, `check_router_repositories.py`, `check_text_sql.py` | CI guards | Yes |
| `purge_retention.py` | Ops cron | Yes, if scheduled on purpose |
| `database/sync.py` | Schema compare/migrate | Yes, with care (`--migrate` writes) |
| `run_worker_dev.py` | Dev auto-reload worker | Dev only |
| `parse_config.py`, `parse_config_keys.py` | Local Cisco parse | Local files only |
| `ise_test.py`, `ise_test_update_tacacs.py`, `ise_test_delete_device.py`, `ise_test_ndg_add.py`, `ise_test_ndg_update.py`, `ise_test_ndg_delete.py` | Smoke tests that **mutate/delete ISE** via the backend API | **Do not run against prod.** Default target is a sandbox ISE. Move to `scripts/dev/` or require an explicit env confirmation. |
| `ise_test_ndg_list.py`, `ise_show_all_devices.py`, `ise_test_devices_by_ndg.py` | Read-only ISE smokes | Lower risk; still hit a live ISE |

### 7.3 Duplicate surface (not dead)

`services/nautobot/metadata_service.py` (`NautobotMetadataService`) and `services/sources/nautobot/metadata_service.py` (`NautobotSourceMetadataService`) both hit Nautobot custom-fields REST. Different call paths (custom-fields router vs source service). Document or consolidate later; do not delete blindly.

### 7.4 Not dead (common false positives)

- `label` / `background` steps — canvas-only, no executor, correct.
- `routers/git/debug.py` + `GitDebugService` — live; should be treated as admin/dev tooling (§6.7).
- `core/dev_tools.py` — real feature flag for OIDC test routes.
- `utils/inventory_converter.py` — imported by Nautobot ops.
- `hatchet/workflows/cache_devices.py` — Hatchet cron, not a Celery leftover.

### 7.5 Dependencies

`requirements.txt` matches runtime imports. No Celery. `python-multipart` is required by FastAPI `UploadFile` (certificates) even if not imported directly.

---

## 8. Production-readiness (non-security)

### 8.1 Tests

**Strength:** 104 unit-test modules. Step executors, RBAC, credentials, OIDC, artifacts, login rate limit, and graph validation are well covered.

**Gaps:**

- `tests/integration/` is **empty** (README only). No test hits a real Postgres + Redis + FastAPI stack.
- Routers with no dedicated tests: cache/hatchet/logging/general settings, certificates, git version-control, RBAC user-access, workflow schedules, update-attribute probe.
- Services without dedicated tests: Redis cache, certificate service, schedule/retention, user service, most git services, `workflow_service` beyond graph validation.
- Executors with weak or no dedicated tests: `filter-output`, `merge-content`, `reachable`, `show-summary`, `get-git-devices`, `get-nautobot-devices`, `get-nautobot-attributes`. `update-nautobot-device` has helper tests only.

For v1, the highest-value additions are: one integration test (login → RBAC → create workflow), OIDC state+redirect_uri, git URL reject `file://`, and settings token encryption once it exists.

### 8.2 Health and operability

- `/health` does not prove the process can reach Postgres or Redis. `init_db()` runs at startup; a later DB outage is invisible to the load balancer.
- Run retention (`RUN_RETENTION_ENABLED`, default false) and `purge_retention.py` exist. Decide the production default before storing large config backups.
- Hatchet worker is a separate process (`scripts/run_worker_dev.py` for dev). A web-only deploy will accept “run” and never execute. Document the required processes: API, worker, Redis, Postgres, Hatchet.

### 8.3 Error contract

Routers that catch exceptions generally use `raise_internal_server_error`. Thin delegators (`routers/workflows.py`) rely on services raising `HTTPException` or on FastAPI’s generic 500. Extend `check_http_500_leaks.py` to `services/` (or ban `HTTPException` in services and use domain exceptions).

### 8.4 Session / DB model for git

`GitRepositoryRepository` + `git_repo_manager` singleton open their own sessions. Under load this is extra pool use and unclear transaction boundaries. Not a security bug; it is the main scalability smell.

---

## 9. Recommended order for a first production release

**Stop-ship (backend)**

1. Encrypt Nautobot/Git tokens at rest (match ISE/pyATS). Keep GET redaction.
2. Make `ENV=production` hard to forget: refuse default secrets and disable `/docs` unless explicitly opted in. Require `CREDENTIAL_ENCRYPTION_KEY`.
3. Git URL scheme allow-list; reject `file://`.
4. Bind OIDC `redirect_uri` to Redis state; allow-list frontend origins.
5. Gate git debug, schema migrate, RBAC wipe, and system-CA install with `ENABLE_DEV_TOOLS` / `ENV=production` (OIDC test is already gated). Set `ENABLE_DEV_TOOLS` unset in prod manifests.
6. Decide Netmiko host policy (inventory-only vs accepted internal pivot) and write it down.

**Before or immediately after first deploy**

7. Add `general_settings:read` on GET.
8. Delete `get_cached_commits`, dead `plugins.py` token models, and the `DeviceImportService` TODO (or implement it).
9. Move `workflow_steps.common.device_template` helpers out of the step package.
10. `/health/ready` (Postgres + Redis).
11. Move mutating `ise_test*.py` under `scripts/dev/` with a guard.
12. Align git repositories with injected `Session`.
13. Production env checklist in the deploy README: `ENV`, `SECRET_KEY`, `INITIAL_PASSWORD`, `CREDENTIAL_ENCRYPTION_KEY`, `DATABASE_PASSWORD`, `ENABLE_DEV_TOOLS` unset, `DOCS_ENABLED=false`, `TRUSTED_PROXY_IPS`, `INSTALL_CERTIFICATE_FILES`, Hatchet worker running.

**Backlog (does not block a cautious internal v1)**

14. Split `StepRunner` and `workflow_run.py`.
15. Split fat Nautobot/ISE ops routers; extract GraphQL query constants from resolvers.
16. JWT denylist if access-token TTL stays at 60 minutes or longer.
17. Default pyATS `verify_ssl=True`.
18. Global 500 handler with `error_id`; extend the leak checker to services.
19. Integration-test scaffold.
20. Update CLAUDE.md: 15 tables, drop Celery, fix the missing `REFACTORING_RAW_SQL.md` link, document injected-session repositories.

---

## 10. Appendix

### 10.1 Router map (`main.py`)

auth, oidc, git (CRUD + ops + VCS + files + debug), source CRUD/ops (git, nautobot, ise, pyats), nautobot custom fields, workflow steps, update-attribute, workflows, runs, schedules, settings, credentials, templates, netmiko, hatchet/cache/logging/general settings, rbac, users, system, certificates.

### 10.2 Production files > 300 lines (complete, excl. tests)

`workflow_run.py`, `step_runner.py`, `git/file_service.py`, `nautobot/devices/interface_workflow.py`, `git/service.py`, `nautobot/devices/update.py`, `git/debug_service.py`, `deploy_rendered_template/executor.py`, `sources/nautobot/ops.py`, `sources/ise/ops.py`, `compare_data/executor.py`, `compare_pyats_snapshot/executor.py`, `get_ise_tacacs_key/executor.py`, `add_to_ise/executor.py`, `nautobot/resolvers/device_resolver.py`, `migrations/auto_schema.py`, `cache/redis_cache_service.py`, `git/operations.py`, `nautobot/devices/common.py`, `store_artifact/executor.py`, `sources/nautobot/query_service.py`, `update_nautobot_device/executor.py`, `execution/run_service.py`, `sources/nautobot/live_query_mixin.py`, `log_attributes/executor.py`, `sources/nautobot/persistence_service.py`, `add_to_nautobot/executor.py`, `sources/nautobot/evaluator.py`, `sources/nautobot/crud.py`, `get_pyats_snapshot/executor.py`, `run_command/executor.py`, `get_ise_devices/executor.py`, `filter_output/executor.py`, `scripts/database/sync.py`, `workflow_steps/common/content_resolver.py`, `workflow_context/attribute_path.py`, `merge_content/executor.py`, `update_ise_tacacs_key/executor.py`, `network/netmiko/connection.py`, `git/auth.py`, `render_jinja_template/executor.py`, `sources/git/git_source_service.py`, `nautobot/devices/creation.py`, `git/cache.py`, `credentials/credentials_service.py`, `auth/oidc_service.py`, `git/connection.py`, `get_device_configs/executor.py`, `nautobot/managers/ip_manager.py`, `get_pyats_config/executor.py`.

### 10.3 Cross-links

- Frontend counterpart: `doc/GROK-20260813-ANALYSIS.md`
- Frontend hardening plan: `doc/refactoring/GROK-20260813-REFACTORING.md`
- Accepted server risks: `doc/SECURITY-NOTES.md`
- Step contracts: `doc/WORKFLOW-STEPS.md`
