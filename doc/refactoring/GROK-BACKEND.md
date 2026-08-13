# Backend production-hardening refactoring plan — 13 August 2026

Source: `doc/GROK-BACKEND-ANALYSIS.md`. This plan covers **P1 stop-ship** items and the small cleanups that must land with them. P2 backlog (JWT denylist, `StepRunner` / `workflow_run.py` splits, fat source-router splits, pyATS `verify_ssl` default, git injected-`Session` rewrite) is out of scope.

Implement **in the order below**. Later items assume earlier contracts. Do not re-analyse call sites — every file, symbol, and replacement is listed.

Accepted risks in `doc/SECURITY-NOTES.md` (`verify_ssl=False`, Netmiko host-key checking, git credentials in argv, pyATS shim over HTTP) stay accepted. Do not “fix” them in this plan.

---

## How to read this document

Each work item has:

- **Before** — current behaviour and the exact code to change.
- **After** — the target contract. Copy the shapes; do not invent parallel APIs.
- **Files** — every path that must change. If a path is not listed, leave it alone.
- **Verify** — how to know the item is done.

Do **not** change workflow-step **executors** (`backend/workflow_steps/*/executor.py`) except the import path in R9. They already load tokens via `SettingsService.get_source_config` / `get_source_config_for_step`. After R1 those methods still return a plaintext `token` **in memory**. Executors must not learn about `credential_id`.

---

## Out of scope

- Splitting `services/execution/step_runner.py` or `hatchet/workflows/workflow_run.py`.
- Splitting `routers/sources/nautobot/ops.py` / `ise/ops.py`.
- Rewriting `GitRepositoryRepository` onto an injected `Session`.
- JWT revocation / denylist.
- Changing ISE or pyATS source config (already encrypted).
- Frontend work (already planned in `doc/refactoring/GROK-20260813-REFACTORING.md`).
- Moving `scripts/ise_test*.py` (ops hygiene, not an API contract).
- CLAUDE.md table-count / Celery wording (docs-only).

---

## Suggested PR sequence

| PR | Items | Why this grouping |
|---|---|---|
| 1 | R1 | Token-at-rest. Updates `test_settings_token_redaction.py`. No HTTP shape change. |
| 2 | R2 | Startup secret guards. Pure functions, easy to test. |
| 3 | R3 | Git URL allow-list. Independent of R1. |
| 4 | R4 | OIDC `redirect_uri` bound to Redis state. |
| 5 | R5 + R6 + R7 | Break-glass kill-switch, Netmiko host policy, `general_settings:read`. |
| 6 | R8 + R9 | Dead code + move `device_template` out of `workflow_steps`. |
| 7 | R10 | `/health/ready`. |
| 8 | R11 | One test module that locks R1–R10. Run it last; it is the release gate. |

---

# R1 — Encrypt Nautobot / Git tokens at rest (P1)

Copy the pyATS pairing: non-secret fields stay in `settings.value`; the token lives in the encrypted `credentials` table. Do **not** add new HTTP routes. `POST/PUT /settings` and `get_source_config` keep their current signatures.

## Before

`backend/services/settings/settings_service.py` persists the raw token:

```python
# create_setting → _normalize_source_value → repo.create(value=…)
# update_setting copies existing token when the incoming token is blank
# get_source_config returns {**(setting.value or {}), "source_id": source_id}
```

`settings.value` for `sources.nautobot.lab` / `sources.git.lab` looks like:

```json
{ "url": "https://…", "token": "nb-secret", "verify_ssl": true, "source_id": "lab", "source_type": "nautobot" }
```

`_redact_source_token` blanks `token` on GET only. `tests/unit/test_settings_token_redaction.py` asserts the ORM/persisted dict still contains `"token": "git-secret"`.

ISE/pyATS already do this correctly (`credential_id` in settings, password in `credentials`). Do not change those services.

## After

### Persist

In `SettingsService.__init__`, also construct `CredentialsService(db)` (same `Session`).

Add module constants (mirror `services/pyats/source_config_service.py`):

```python
_TOKEN_SOURCE_TYPES = frozenset({"nautobot", "git"})
_TOKEN_USERNAME = {
    "nautobot": "nautobot-token",
    "git": "git-token",
}

def _credential_name(source_type: str, source_id: str) -> str:
    return f"{source_type}-{source_id}"
```

In `_normalize_source_value` (called from create and update), after URL validation and `ensure_value_source_id`:

1. If `source_type` is not in `_TOKEN_SOURCE_TYPES`, return as today.
2. Pop `"token"` and `"token_configured"` from the value dict. Never persist either.
3. Do **not** create the credential here (no `self` on a staticmethod). Change `_normalize_source_value` to an instance method, or return `(value_without_token, token_or_none)` and let `create_setting` / `update_setting` own the credential write.

`create_setting` for nautobot/git:

```python
value, token = self._normalize_source_value(data.key, data.value)
if parsed in _TOKEN_SOURCE_TYPES:
    if not (token or "").strip():
        raise HTTPException(400, detail="token is required")
    credential = self._credentials.create_credential(
        name=_credential_name(source_type, source_id),
        username=_TOKEN_USERNAME[source_type],
        cred_type="generic",
        password=token,
        source=source_type,          # "nautobot" | "git"
        visibility="global",
    )
    value["credential_id"] = credential["id"]
# persist value — no "token" key
```

`update_setting` for nautobot/git:

- Incoming blank/missing `token`: keep existing `credential_id`; do not call `update_credential`. If the row is **legacy** (has plaintext `token`, no `credential_id`), migrate: create credential from the existing token, drop `token`, set `credential_id`.
- Incoming non-blank `token`: if `credential_id` exists, `update_credential(credential_id, password=token)`; else create as on create.
- Strip `token` / `token_configured` before persist.

`delete_setting`: after `repo.delete`, if `setting.value` had `credential_id`, `delete_credential` (ignore `CredentialNotFoundError`), same as `PyATSSourceConfigService.delete_source`.

### Read

`_redact_source_token`:

```python
token_configured = bool(raw.get("credential_id")) or bool(str(raw.get("token") or "").strip())
redacted = {k: v for k, v in raw.items() if k not in {"token", "credential_id"}}
redacted["token"] = ""
redacted["token_configured"] = token_configured
return redacted
```

`get_source_config` / `get_source_config_for_step` (executors and routers):

```python
value = dict(setting.value or {})
credential_id = value.pop("credential_id", None)
if credential_id is not None:
    value["token"] = self._credentials.get_decrypted_password(credential_id)
# legacy plaintext row: leave value["token"] as stored
return {**value, "source_id": source_id}
```

Do not raise if a legacy row still has plaintext `token` and no `credential_id`. Next update migrates it.

### Tests that must change in this PR

`backend/tests/unit/test_settings_token_redaction.py`:

- `test_create_*_persists_token_*`: assert persisted value has `credential_id`, **no** `token`. Mock `CredentialsService.create_credential` to return `{"id": 99}`.
- `get_source_config` assertions: mock `get_decrypted_password` → `"git-secret"` / `"nb-secret"`.
- `test_update_blank_token_keeps_previous_secret`: existing row has `credential_id=99` and no token; blank PUT must not call `update_credential`; `get_source_config` still decrypts 99.
- `test_list_redacts_*`: `assert "credential_id" not in` the response value; `token_configured is True` when `credential_id` is set.
- Keep the `app.misc` token-passthrough assertion (R1 does not redact arbitrary keys).

## Files

- **Edit:** `backend/services/settings/settings_service.py`
- **Edit:** `backend/tests/unit/test_settings_token_redaction.py`
- **Edit:** `backend/services/ise/source_config_service.py` — delete the phrase “unlike the Nautobot token today” from the module docstring.

## Verify

- Create a Nautobot source via `POST /settings`: GET returns `token=""` + `token_configured=true`; SQL `settings.value` has `credential_id` and no `token`; `credentials.password_encrypted` is non-null.
- Blank PUT keeps the old token (preview / test-connection with `source_id` still works).
- New PUT token rotates the credential password; old ciphertext no longer decrypts to the old token.
- Workflow steps that call `get_source_config_for_step("nautobot"|"git", …)` still receive `config["token"]` as plaintext. Do not edit executors.
- Existing ISE/pyATS source tests still pass.

---

# R2 — Production secret guards (P1)

## Before

`backend/core/config.py`:

```python
self.environment = environ.get("ENV", "development")
self.docs_enabled = self._get_bool("DOCS_ENABLED", self.environment == "development")
# …
self.credential_encryption_key = environ.get("CREDENTIAL_ENCRYPTION_KEY", "")
self.database_password = environ.get("DATABASE_PASSWORD", "postgres")
```

`_get_secret_key` / `_validate_initial_password` only run when `environment != "development"`. `CREDENTIAL_ENCRYPTION_KEY` and `DATABASE_PASSWORD` are never required. `CredentialsService` falls back to `SECRET_KEY`.

`docker/Dockerfile.all-in-one` sets `NODE_ENV=production` but not `ENV=production`. `docker/docker-compose.yml` and both `.env.example` files set `ENV=development`.

`settings = Settings()` at import time makes the class hard to unit-test. Extract the checks as pure functions.

## After

1. Add `backend/core/production_guards.py` (pure, no `environ` reads except through arguments):

```python
DEFAULT_SECRET_KEY = "change-in-production-use-at-least-32-characters"
DEFAULT_INITIAL_PASSWORD = "admin"
WEAK_DATABASE_PASSWORDS = frozenset({"", "postgres", "password"})

def validate_non_development_secrets(
    *,
    environment: str,
    secret_key: str,
    initial_password: str,
    credential_encryption_key: str,
    database_password: str,
) -> None:
    if environment == "development":
        return
    if secret_key == DEFAULT_SECRET_KEY:
        raise RuntimeError("SECRET_KEY must be configured outside development")
    if initial_password == DEFAULT_INITIAL_PASSWORD:
        raise RuntimeError("INITIAL_PASSWORD must be configured outside development")
    if not credential_encryption_key.strip():
        raise RuntimeError("CREDENTIAL_ENCRYPTION_KEY must be configured outside development")
    if credential_encryption_key == secret_key:
        raise RuntimeError("CREDENTIAL_ENCRYPTION_KEY must differ from SECRET_KEY")
    if database_password in WEAK_DATABASE_PASSWORDS:
        raise RuntimeError("DATABASE_PASSWORD must be configured outside development")
```

2. `Settings.__init__` calls `validate_non_development_secrets(...)` once at the end (replace the two existing private methods; keep `_get_secret_key` as a reader only).

3. `resolve_credential_secret` in `core/crypto.py` is unchanged for development. In production the empty-key case can no longer happen because startup failed.

4. Docker / env files:

- `docker/Dockerfile.all-in-one` and `docker/Dockerfile.basic`: add `ENV ENV=production` next to `NODE_ENV=production`.
- Do **not** change `docker/docker-compose.yml` or `.env.example` (`ENV=development` is correct for local compose).
- `docker/DOCKER.md` already documents `-e ENV=production`; leave it.

5. Keep `docs_enabled` default `environment == "development"`. Production with `ENV=production` already turns docs off unless `DOCS_ENABLED=true`.

## Files

- **Add:** `backend/core/production_guards.py`
- **Edit:** `backend/core/config.py` (call the helper; delete `_validate_initial_password` body / fold `_get_secret_key` check into the helper)
- **Edit:** `docker/Dockerfile.all-in-one`, `docker/Dockerfile.basic`

## Verify

- `ENV=development` + default secrets: process starts (local dev).
- `ENV=production` + default `SECRET_KEY`: `RuntimeError` at import.
- `ENV=production` + good `SECRET_KEY` + missing `CREDENTIAL_ENCRYPTION_KEY`: `RuntimeError`.
- `ENV=production` + encryption key equal to `SECRET_KEY`: `RuntimeError`.
- `ENV=production` + `DATABASE_PASSWORD=postgres`: `RuntimeError`.
- R11 will lock these cases without importing `core.config.settings`.

---

# R3 — Git remote URL allow-list (P1)

## Before

`backend/core/safe_urls.py` `validate_outbound_http_url` is used for Nautobot/ISE/pyATS HTTP. Git is skipped:

```python
# settings_service.py
if source_type not in ("nautobot", "ise"):
    return value
```

`services/sources/git/git_source_service.py` `test_connection` and `services/git/connection.py` `_run_clone_test` pass the user URL to `git clone` with no scheme check. `file://`, bare paths, and internal HTTP all work.

## After

Add to `backend/core/safe_urls.py` (keep one module; do not add `safe_git.py`):

```python
_ALLOWED_GIT_SCHEMES = frozenset({"https", "ssh", "git+ssh"})

def validate_git_remote_url(url: str, *, resolve_dns: bool = True) -> str:
    """Return a normalized git remote or raise UnsafeURLError.

    Allows https (via validate_outbound_http_url), ssh, git+ssh, and
    scp-like git@host:path. Rejects file://, http://, and bare filesystem paths.
    """
```

Rules (copy these, do not invent extras):

| Input | Result |
|---|---|
| `https://git.example.com/org/repo.git` | OK — run through `validate_outbound_http_url` |
| `ssh://git@git.example.com/org/repo.git` | OK if host is present |
| `git@git.example.com:org/repo.git` | OK (scp-like; no scheme) |
| `http://…` | `UnsafeURLError` (“use https or ssh”) |
| `file:///etc/passwd` / `file://…` | `UnsafeURLError` |
| `/var/git/repo.git` or `C:\git\repo` | `UnsafeURLError` |
| empty / whitespace | `UnsafeURLError` (“URL is required”) |
| `https://user:pass@host/repo.git` | `UnsafeURLError` (existing “no embedded credentials” rule) |

Call sites — validate **before** `_build_auth_url` / `subprocess.run`:

1. `SettingsService._validate_source_url`: if `source_type == "git"` and `value.get("url")` is set, `validate_git_remote_url(str(url))`.
2. `git_source_service.test_connection`: at the top, after the empty-URL check, `validate_git_remote_url(public_url)`. On `UnsafeURLError` return `{"success": False, "message": str(exc)}` (do not clone).
3. `services/git/connection.py` clone-test path: same, raise or return the existing `GitConnectionTestResponse(success=False, message=…)`.
4. Any other `git clone` / `git ls-remote` entry that takes a user URL in `services/git/` or `services/sources/git/` — apply the same helper. Do not change GitPython internals.

Client-facing clone **stderr**: keep `_redact_secrets`. In `connection.py` the failure `message` today is `f"Git connection failed: {result.stderr}"`. Change to `"Git connection failed"` and put the redacted stderr only in logs / `details` if you already have a details field. `git_source_service.test_connection` already redacts; leave its message shape.

## Files

- **Edit:** `backend/core/safe_urls.py`
- **Edit:** `backend/services/settings/settings_service.py` (`_validate_source_url`)
- **Edit:** `backend/services/sources/git/git_source_service.py`
- **Edit:** `backend/services/git/connection.py`
- **Edit:** `backend/tests/unit/test_source_connection_tests.py` — add `file://` and `http://` cases that must **not** call `subprocess.run`

## Verify

- `test_connection(url="file:///tmp/x")` → `success=False`, `subprocess.run` not called.
- `https://git.example.com/org/repo.git` still clones (mocked).
- Creating `sources.git.lab` with `url=file:///tmp/x` via `SettingsService.create_setting` → HTTP 400.

---

# R4 — Bind OIDC `redirect_uri` to Redis state (P1)

## Before

`backend/routers/oidc.py` `_build_login_response`:

```python
cache.set(f"oidc-state:{state_with_provider}", "1", ttl_seconds=OIDC_STATE_TTL_SECONDS)
```

`handle_callback` checks that the Redis key exists, then uses `body.redirect_uri or ""` for the token exchange. The stored value is unused. Any `redirect_uri` the client sends is forwarded to the IdP.

`OIDCCallbackRequest.redirect_uri` is optional. `OIDC_STATE_TTL_SECONDS = 600`.

## After

1. Add `backend/core/oidc_redirect.py`:

```python
from urllib.parse import urlparse

def validate_oidc_redirect_uri(
    redirect_uri: str,
    *,
    allowlist: list[str],
    environment: str,
    dev_tools: bool = False,
) -> str:
    """Return the URI or raise ValueError."""
```

Rules:

- URI must be `http` or `https`, no userinfo, no fragment.
- If `allowlist` is non-empty: **exact string match** against one entry (after strip).
- If `allowlist` is empty and `environment == "development"`: allow `http://localhost` / `http://127.0.0.1` with path `/login/callback` or `/login/oidc-test-callback` or `/tools/oidc-test-callback` (the real frontend paths). Reject everything else.
- If `allowlist` is empty and `environment != "development"`: raise (`OIDC_REDIRECT_URI_ALLOWLIST` is required).
- `dev_tools=True` (test-login only): still require http(s) and no userinfo; skip allowlist (route is already 404 when `ENABLE_DEV_TOOLS` is off).

2. `Settings`: `self.oidc_redirect_uri_allowlist = self._get_csv("OIDC_REDIRECT_URI_ALLOWLIST", "")`.

3. `_build_login_response` (production login, **not** test-login):

```python
redirect_uri = validate_oidc_redirect_uri(
    redirect_uri,
    allowlist=settings.oidc_redirect_uri_allowlist,
    environment=settings.environment,
)
# …
cache.set(f"oidc-state:{state_with_provider}", redirect_uri, ttl_seconds=OIDC_STATE_TTL_SECONDS)
```

Test-login calls `_build_login_response` today. Add a `*, relax_redirect: bool = False` flag and pass `dev_tools=True` only from `initiate_test_login`.

4. `handle_callback`:

```python
stored_redirect = cache.get(state_key)
if stored_redirect is None:
    raise HTTPException(400, detail="Invalid state")
cache.delete(state_key)
redirect_uri = body.redirect_uri or ""
if redirect_uri != stored_redirect:
    raise HTTPException(400, detail="Invalid redirect_uri")
# exchange with redirect_uri
```

Redis value is the URI string, not `"1"`. TTL stays 600.

5. Document `OIDC_REDIRECT_URI_ALLOWLIST` in `backend/.env.example` as a commented line, e.g. `# OIDC_REDIRECT_URI_ALLOWLIST=https://manus.example.com/login/callback`.

## Files

- **Add:** `backend/core/oidc_redirect.py`
- **Edit:** `backend/core/config.py` (allowlist field)
- **Edit:** `backend/routers/oidc.py`
- **Edit:** `backend/.env.example` (comment only)

## Verify

- Happy path: login stores URI; callback with the same URI succeeds (existing OIDC tests + a new router-level test with a fake cache).
- Callback with a different `redirect_uri` than Redis: 400, no token exchange.
- Production + empty allowlist: login 400.
- Development + `http://localhost:3000/login/callback`: allowed.
- Development + `https://evil.example/callback`: rejected.

---

# R5 — Gate break-glass HTTP behind `ENABLE_DEV_TOOLS` (P1)

OIDC test-login / debug already return 404 when `dev_tools_enabled()` is false. Copy that pattern. Do not invent a second flag.

## Before

| Route | Gating |
|---|---|
| `POST /auth/oidc/{id}/test-login`, `GET /auth/oidc/debug` | `ENABLE_DEV_TOOLS` + RBAC |
| `POST /git-repositories/{id}/debug/{read,write,delete,push}` | `git.debug:execute` only |
| `GET /git-repositories/{id}/debug/diagnostics` | `git.debug:read` only |
| `POST /system/schema/migrate` | `system.database:write` |
| `POST /system/rbac/seed` | `system.rbac:write` |
| `POST /certificates/add-to-system` | `system.certificates:write` (`INSTALL_CERTIFICATE_FILES` is only checked at **startup** in `core/cert_installer.py`) |

`routers/git/main.py` always `include_router(debug_router)`.

## After

Add one helper next to `dev_tools_enabled()` in `backend/core/dev_tools.py`:

```python
from fastapi import HTTPException, status

def require_dev_tools() -> None:
    if not dev_tools_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
```

Use it as `dependencies=[Depends(require_dev_tools), Depends(require_permission(...))]` on:

- Every route in `backend/routers/git/debug.py` (keep the existing RBAC deps).
- `POST /system/schema/migrate` in `routers/system.py`. Leave `GET /system/schema/status` as-is (read-only).
- `POST /system/rbac/seed` in `routers/system.py`.
- `POST /certificates/add-to-system` in `routers/certificates.py`. Upload / scan / delete stay RBAC-only (they write under `config/certs/`, not the system store).

Optional belt: in `routers/git/main.py`, only `include_router(debug_router)` when `dev_tools_enabled()`. Still put `require_dev_tools` on the routes so a stale import cannot serve them.

Do **not** change `ENABLE_DEV_TOOLS` default (unset = off).

## Files

- **Edit:** `backend/core/dev_tools.py`
- **Edit:** `backend/routers/git/debug.py`
- **Edit:** `backend/routers/git/main.py`
- **Edit:** `backend/routers/system.py`
- **Edit:** `backend/routers/certificates.py`

## Verify

- Unset `ENABLE_DEV_TOOLS`: `POST /api/system/schema/migrate` → 404 even as admin; git debug write → 404; OIDC test-login still 404.
- `ENABLE_DEV_TOOLS=true` + correct permission: same routes work as today.
- `GET /api/system/schema/status` still 200 with `system.database:read`.

---

# R6 — Netmiko preview host policy (P1)

## Before

`backend/routers/netmiko.py` `run_commands` / `get-configs` pass `payload.host` to `NetmikoService` after RBAC `netmiko:execute`. No host check. `models/netmiko.py` only requires `min_length=1`.

Host-key checking stays accepted (`SECURITY-NOTES.md`). This item is **where** the backend will SSH, not whether it verifies the key.

## After

Add `backend/core/safe_hosts.py`:

```python
def validate_netmiko_preview_host(
    host: str,
    *,
    environment: str,
    allow_arbitrary: bool,
) -> str:
    """Return a stripped host or raise ValueError."""
```

Rules:

- Strip; reject empty.
- Reject if the host is a literal IP that is unspecified, multicast, link-local, or loopback (reuse the same IP predicates as `safe_urls._assert_ip_allowed`, but **do** reject loopback even when `ALLOW_LOOPBACK_SOURCE_URLS` is set — preview is not a source).
- Reject hostnames `metadata.google.internal`, `metadata.google.com`.
- If `environment != "development"` and `allow_arbitrary` is false: raise `ValueError("Netmiko preview to arbitrary hosts is disabled")`.
- If development **or** `allow_arbitrary`: accept hostname / RFC1918 / public IP.

`Settings`: `self.allow_netmiko_arbitrary_hosts = self._get_bool("ALLOW_NETMIKO_ARBITRARY_HOSTS", self.environment == "development")`.

In both netmiko handlers, before `NetmikoService`:

```python
try:
    host = validate_netmiko_preview_host(
        payload.host,
        environment=settings.environment,
        allow_arbitrary=settings.allow_netmiko_arbitrary_hosts,
    )
except ValueError as exc:
    raise HTTPException(status_code=400, detail=str(exc)) from exc
```

Use `host` (not `payload.host`) in the service call.

Workflow-step Netmiko executors (`run_command`, `deploy_rendered_template`, …) are **unchanged** — they target inventory devices, not this preview API.

Document `ALLOW_NETMIKO_ARBITRARY_HOSTS` as a commented line in `backend/.env.example`.

Add one sentence to `doc/SECURITY-NOTES.md` under the Netmiko heading: preview SSH is denied in production unless `ALLOW_NETMIKO_ARBITRARY_HOSTS=true`; host-key checking remains accepted.

## Files

- **Add:** `backend/core/safe_hosts.py`
- **Edit:** `backend/core/config.py`
- **Edit:** `backend/routers/netmiko.py`
- **Edit:** `backend/.env.example`
- **Edit:** `doc/SECURITY-NOTES.md`
- **Edit:** `backend/tests/unit/test_netmiko_get_configs_router.py` — set `allow_netmiko_arbitrary_hosts=True` in the test app / monkeypatch so existing preview tests still pass

## Verify

- Development: preview to `10.0.0.1` still works (existing router test).
- `environment="production"`, `allow_arbitrary=False`, host `10.0.0.1`: 400, `NetmikoService` not called.
- Host `169.254.169.254` or `metadata.google.internal`: 400 in every environment.

---

# R7 — `GET /general/settings` requires `general_settings:read`

## Before

`backend/routers/general_settings.py`:

```python
router = APIRouter(..., dependencies=[Depends(get_current_user)])

@router.get("/settings", response_model=GeneralSettingsResponse)
async def get_general_settings(...):
    return service.get_settings()

@router.put(..., dependencies=[Depends(require_permission("general_settings", "write"))])
```

Any authenticated user can read export path / session timeout.

## After

```python
@router.get(
    "/settings",
    response_model=GeneralSettingsResponse,
    dependencies=[Depends(require_permission("general_settings", "read"))],
)
```

Keep the router-level `get_current_user`. Do not change the PUT. Confirm `general_settings:read` already exists in `services/auth/rbac_seed.py`; if it does not, add it next to the existing `general_settings:write` seed entry (same resource, action `"read"`).

## Files

- **Edit:** `backend/routers/general_settings.py`
- **Edit:** `backend/services/auth/rbac_seed.py` — only if `general_settings:read` is missing

## Verify

- User without `general_settings:read`: GET 403.
- User with the permission: GET 200, same body as today.
- PUT still requires `write`.

---

# R8 — Delete dead code

## Before

1. `backend/routers/git/operations.py` `get_cached_commits` (lines 26–40) — defined, never called, marked DEPRECATED.
2. `backend/services/nautobot/devices/update.py` around 241–243:

```python
if create_if_missing:
    # TODO: Call DeviceImportService to create device
    raise ValueError("Device not found and create_if_missing not yet implemented")
```

`create_if_missing` is a parameter on the public update method. `DeviceImportService` does not exist.

3. `backend/models/plugins.py` `DeviceSelectionPreviewRequest` and `FieldValuesRequest` (token-bearing). Live types are in `models/sources_nautobot.py`. `routers/workflow_steps.py` only imports `PluginDefinition` / list/registry models.

## After

1. Delete `get_cached_commits` entirely. Do not replace callers (there are none).
2. Remove the `create_if_missing` parameter from `DeviceUpdateService` public/private methods and the `if create_if_missing:` branch. Update the docstring that mentions `DeviceImportService`. Grep for `create_if_missing` and delete remaining kwargs at call sites (likely only `update.py` itself).
3. Delete `DeviceSelectionPreviewRequest`, `FieldValuesRequest`, and any types used **only** by those two models in `models/plugins.py` (`DevicePreview` / `DeviceSelectionPreviewResponse` / `FieldOption` / `FieldOptionsResponse` / `FieldValuesResponse` if nothing else imports them). Grep before deleting. Keep `LogicalOperationRequest` if other plugin types still use it.

## Files

- **Edit:** `backend/routers/git/operations.py`
- **Edit:** `backend/services/nautobot/devices/update.py` (+ any caller that passes `create_if_missing`)
- **Edit:** `backend/models/plugins.py`

## Verify

- `rg get_cached_commits backend` → no matches.
- `rg DeviceImportService backend` → no matches.
- `rg DeviceSelectionPreviewRequest backend` → no matches.
- `python -m pytest backend/tests/unit/test_nautobot_update_fields.py backend/tests/unit/test_plugin_registry_capabilities.py` pass.

---

# R9 — Move `device_template` out of `workflow_steps`

CLAUDE.md: external code must never import `workflow_steps` packages; only `StepRunner` / `step_registry` call executors. `git_sink.py` and `attribute_path.py` violate that.

## Before

`backend/workflow_steps/common/device_template.py` is imported by:

| Importer | Allowed today? |
|---|---|
| `workflow_steps/*/executor.py` and `common/jinja_render.py` | Yes (inside the step package) |
| `services/artifacts/sinks/git_sink.py` | **No** |
| `services/workflow_context/attribute_path.py` | **No** |
| `tests/unit/test_device_template.py` | Test |

## After

1. **Move** the file to `backend/services/workflow_context/device_template.py` (same contents, same public functions).
2. Replace every import:

```python
from services.workflow_context.device_template import (
    build_template_context,
    sanitize_relative_path,
    # …whatever that file imported
)
```

3. Leave a **one-line** shim so any missed import fails loudly in grep, not at runtime? **No.** Delete `workflow_steps/common/device_template.py`. Fix all imports in the same PR.
4. Update `tests/unit/test_device_template.py` import path only. Do not change assertions.

## Files

- **Add:** `backend/services/workflow_context/device_template.py` (move)
- **Delete:** `backend/workflow_steps/common/device_template.py`
- **Edit imports:** `services/artifacts/sinks/git_sink.py`, `services/workflow_context/attribute_path.py`, `workflow_steps/common/jinja_render.py`, `workflow_steps/git_push/executor.py`, `workflow_steps/store_artifact/executor.py`, `workflow_steps/compare_data/executor.py`, `workflow_steps/compare_data/reference_reader.py`, `workflow_steps/compare_pyats_snapshot/executor.py`, `workflow_steps/log_attributes/executor.py`, `tests/unit/test_device_template.py`

## Verify

- `rg "workflow_steps.common.device_template" backend` → no matches.
- `rg "from workflow_steps" backend/services` → only `services/execution/step_registry.py`.
- `python -m pytest backend/tests/unit/test_device_template.py backend/tests/unit/test_attribute_path.py backend/tests/unit/test_git_artifact_sink.py backend/tests/unit/test_jinja_render.py` pass.

---

# R10 — `/health/ready`

## Before

`backend/main.py`:

```python
@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
```

No DB or Redis check. Load balancers cannot tell a process with a dead Postgres from a healthy one.

## After

Keep `/health` exactly as it is (liveness).

Add `backend/models/health.py`:

```python
class ReadyCheck(BaseModel):
    ok: bool
    error: str | None = None

class ReadyResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    database: ReadyCheck
    redis: ReadyCheck
```

Add `GET /health/ready` on the same app (no auth, no `/api` prefix — same as `/health`):

```python
@app.get("/health/ready", tags=["health"], response_model=ReadyResponse)
async def health_ready() -> ReadyResponse:
    ...
```

Checks:

- Database: `SessionLocal()` + `session.execute(text("SELECT 1"))` — this is the documented health-check exception in CLAUDE.md (`core/database.py` / health). Do **not** put `text()` in a router if you can avoid it: add `core/database.py` `def ping_database() -> None` that runs `SELECT 1` and raises on failure. The route only calls `ping_database()`.
- Redis: `service_factory.build_cache_service()`. If `None`, `redis.ok = False`, `error="unconfigured"`. If present, call an existing ping/get if the cache service has one; otherwise `SET`/`GET` a key `health:ready` with TTL 10s.

If either check fails: HTTP **503**, body still `ReadyResponse` with `status="unavailable"`. If both pass: 200, `status="ok"`.

Do not check Hatchet (no cheap local ping in this codebase).

## Files

- **Add:** `backend/models/health.py`
- **Edit:** `backend/core/database.py` (`ping_database`)
- **Edit:** `backend/main.py`
- **Edit:** `backend/services/cache/redis_cache_service.py` only if you need a public `ping()` — prefer adding `def ping(self) -> None` there rather than using raw redis in `main.py`

## Verify

- Process up, Postgres + Redis up: `GET /health` → 200 `{"status":"ok"}`; `GET /health/ready` → 200, both `ok: true`.
- Postgres down: `/health` still 200; `/health/ready` → 503, `database.ok=false`.

---

# R11 — Release-gate tests

This is the item that proves R1–R10. One new module, plus the existing files already edited in earlier PRs. Do **not** start a live Postgres/Redis/Hatchet stack. Use the same in-memory SQLite + mocks the rest of `tests/unit` uses.

## After — add `backend/tests/unit/test_production_hardening.py`

Copy the shapes. Each class maps to one R item. If a helper is missing, the test fails — that is the point.

```python
"""Release gate for doc/refactoring/GROK-BACKEND.md (R1–R10)."""
```

### `TestR1TokenAtRest`

Use `SettingsService` + mocked `SettingsRepository` + mocked `CredentialsService` (same style as `test_settings_token_redaction.py`).

- `test_create_persists_credential_id_not_token`
- `test_get_source_config_decrypts_token`
- `test_get_setting_hides_credential_id_and_token`
- `test_update_blank_token_does_not_rotate_credential`
- `test_delete_setting_deletes_linked_credential`
- `test_legacy_plaintext_row_still_resolves_in_get_source_config`

### `TestR2ProductionGuards`

Import `validate_non_development_secrets` only (do not construct `Settings()`).

- development + defaults → no raise
- production + default `SECRET_KEY` → `RuntimeError`
- production + empty `CREDENTIAL_ENCRYPTION_KEY` → `RuntimeError`
- production + encryption key == `SECRET_KEY` → `RuntimeError`
- production + `DATABASE_PASSWORD="postgres"` → `RuntimeError`
- production + distinct strong secrets → no raise

### `TestR3GitRemoteUrl`

Import `validate_git_remote_url`, `UnsafeURLError`. Monkeypatch DNS if `https` would resolve.

- accept `https://git.example.com/org/repo.git` (patch `validate_outbound_http_url` or `socket.getaddrinfo`)
- accept `git@git.example.com:org/repo.git`
- reject `file:///tmp/repo.git`
- reject `http://git.example.com/org/repo.git`
- reject `/var/git/repo.git`
- `git_source_service.test_connection(url="file:///tmp/x")` does not call `subprocess.run`

### `TestR4OidcRedirect`

Import `validate_oidc_redirect_uri`.

- development + empty allowlist + `http://localhost:3000/login/callback` → same string
- development + `https://evil.example/callback` → `ValueError`
- production + empty allowlist → `ValueError`
- production + allowlist exact match → OK
- production + allowlist miss → `ValueError`

Add a small callback test with a fake cache dict (extract the compare/delete logic if the router is too heavy to import — prefer testing `validate_oidc_redirect_uri` plus a 10-line helper `assert_redirect_matches_state(stored, incoming) -> None` in `core/oidc_redirect.py` used by the router).

### `TestR5DevToolsGate`

- `dev_tools_enabled()` is false when env unset (monkeypatch `os.environ`).
- `require_dev_tools()` raises `HTTPException` with `status_code=404`.
- FastAPI `TestClient` on a tiny app that includes `system_router` **or** call the migrate endpoint with `dev_tools_enabled` patched to `False`: 404.

Do not boot the full `main.app` (it opens Postgres). Include only `routers.system.router` like `test_settings_token_redaction.py` does for nautobot ops.

### `TestR6NetmikoHost`

Import `validate_netmiko_preview_host`.

- `10.1.2.3` + development → `"10.1.2.3"`
- `169.254.169.254` → `ValueError`
- `metadata.google.internal` → `ValueError`
- `10.1.2.3` + production + `allow_arbitrary=False` → `ValueError`
- `10.1.2.3` + production + `allow_arbitrary=True` → OK

### `TestR7GeneralSettingsRead`

`TestClient` on `general_settings.router` with `get_current_user` overridden and `RBACService.has_permission` mocked.

- permission denied → 403
- permission granted → 200

Follow `test_credentials_router.py` / `test_require_permission_inactive_user.py` for the override pattern.

### `TestR8DeadSymbols`

AST/import checks, no behaviour:

```python
def test_get_cached_commits_removed():
    import routers.git.operations as ops
    assert not hasattr(ops, "get_cached_commits")

def test_plugins_has_no_token_preview_models():
    import models.plugins as plugins
    assert not hasattr(plugins, "DeviceSelectionPreviewRequest")
    assert not hasattr(plugins, "FieldValuesRequest")
```

### `TestR9StepBoundary`

```python
def test_services_do_not_import_workflow_steps_except_registry():
    # read files as text or import modules and check __module__
```

Practical version: import `services.artifacts.sinks.git_sink` and `services.workflow_context.attribute_path` and assert `'workflow_steps'` not in `sys.modules` **after** a fresh import in a subprocess — too fragile.

Instead:

```python
from pathlib import Path

SERVICES = Path("backend/services")

def test_no_workflow_steps_import_outside_registry():
    allowed = {"execution/step_registry.py"}
    offenders = []
    for path in SERVICES.rglob("*.py"):
        rel = path.relative_to(SERVICES).as_posix()
        if rel in allowed:
            continue
        text = path.read_text()
        if "workflow_steps" in text:
            offenders.append(rel)
    assert offenders == []
```

Resolve `SERVICES` from `Path(__file__).resolve().parents[2] / "services"` so the test does not depend on cwd.

### `TestR10Ready`

- `ping_database` success: mock session.
- `GET /health/ready` on a tiny FastAPI app with `health_ready` and mocked `ping_database` + cache ping: 200 vs 503.

If wiring `health_ready` is awkward, test `ping_database` and a new `build_ready_response(db_ok, redis_ok) -> tuple[int, ReadyResponse]` extracted from `main.py` so the status-code table is unit-tested:

| db | redis | HTTP | status |
|---|---|---|---|
| True | True | 200 | ok |
| False | True | 503 | unavailable |
| True | False | 503 | unavailable |

## Files

- **Add:** `backend/tests/unit/test_production_hardening.py`
- Helpers extracted only if the router is untestable without them: `assert_redirect_matches_state` in `core/oidc_redirect.py`, `build_ready_response` next to the ready route (put the function in `backend/services/health/ready.py` if you extract — do not grow `main.py`).

## Verify (this is the gate)

From `backend/` with the project venv:

```bash
python -m pytest tests/unit/test_production_hardening.py -q
python -m pytest tests/unit/test_settings_token_redaction.py tests/unit/test_source_connection_tests.py tests/unit/test_oidc_service.py tests/unit/test_netmiko_get_configs_router.py tests/unit/test_device_template.py tests/unit/test_attribute_path.py tests/unit/test_ise_source_config_service.py tests/unit/test_pyats_source_config_service.py -q
python scripts/check_http_500_leaks.py
python scripts/check_text_sql.py
python scripts/check_router_repositories.py
python scripts/check_asyncio_run.py
```

All of the above must pass. `test_production_hardening.py` failing means an R item was skipped or the contract drifted.

---

## Implementation notes (do not skip)

- R1 must land before any new Nautobot/Git source is created in a shared environment. Legacy plaintext rows keep working until the next PUT.
- R2 will **break** a container that sets `ENV=production` without `CREDENTIAL_ENCRYPTION_KEY`. That is intended. Set the key before flipping `ENV`.
- R5 hides migrate/reseed in production. Schema changes go through `scripts/database/sync.py` / the existing migration path, not the HTTP tool.
- R6 disables template-editor SSH preview in production until ops sets `ALLOW_NETMIKO_ARBITRARY_HOSTS=true`. Workflow runs are unaffected.
- Do not add CORS. Do not add `response_model` drive-bys. Do not split files listed in Out of scope.
