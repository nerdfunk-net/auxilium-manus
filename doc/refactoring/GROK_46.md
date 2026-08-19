# GROK_46 Refactoring Plan

**Source:** `doc/analysis/GROK_46.md` high and medium findings.  
**Goal:** Implement this document top-to-bottom with no further codebase analysis.  
**Out of scope (already accepted in `doc/SECURITY-NOTES.md`):** Netmiko SSH host-key checking, Nautobot/ISE `verify_ssl=False`, git HTTPS credentials in process argv, pyATS shim credentials over plain HTTP.

Low findings, dead-code deletions, and god-object file splits (`step_runner.py`, `workflow_run.py`) are **not** in this plan.

---

## How to implement

- Apply items **in the numbered order** (later items depend on earlier ones).
- Keep public HTTP status codes and 4xx `detail` strings identical unless an item explicitly says the contract changes (only **H4** 5xx payloads and **M6** git error bodies).
- Do not add CORS. Do not import repositories from routers. Do not call `sqlalchemy.text()` outside the existing allow-list. Do not use f-string logging. Do not put `str(e)` in 5xx `HTTPException.detail`.
- After each item: run the tests listed in that item from `backend/` with `../.venv/bin/python -m pytest <paths>`.
- After the last item: run `../.venv/bin/python -m pytest tests/unit` and the four `scripts/check_*.py` guards.

---

## Work order

| ID | Severity | Item |
|----|----------|------|
| H1 | High | Git SSH host-key checking |
| H2 | High | SSH git remote SSRF / IP policy |
| H3 | High | RBAC anti-elevation |
| H4 | High | Domain exceptions instead of `HTTPException` in services |
| H5 | High | Thin routers (git ops, Netmiko preview, Nautobot/ISE/git source ops, system) |
| M1 | Medium | Refuse `ENABLE_DEV_TOOLS` outside development |
| M2 | Medium | Never relax OIDC redirect validation |
| M3 | Medium | Dashboard `require_permission` |
| M4 | Medium | Load step `get_config()` via plugin registry |
| M5 | Medium | Request-scoped Git repository DB sessions |
| M6 | Medium | Sanitize git health / connection-test / file 4xx error bodies |
| M7 | Medium | Login limiter fail-closed outside development; require Redis password |
| M8 | Medium | Harden `TRUSTED_PROXY_IPS` parsing |
| M9 | Medium | Redact secret-named keys in run output |
| M10 | Medium | TLS-disable WARNING on Mattermost / pyATS / git HTTPS; pyATS `verify_ssl` default True |
| M11 | Medium | Refuse `ALLOW_NETMIKO_ARBITRARY_HOSTS` outside development |
| M12 | Medium | Move template credential visibility check into `TemplatesService` |

H5 includes the templates router helper (analysis §3.2) as **M12** so H5 stays focused on the fat files.

---

## H1 — Git SSH host-key checking

**Files:** create `backend/services/git/ssh_command.py`; edit `backend/services/git/connection.py`, `backend/services/git/auth.py`; add `backend/tests/unit/test_git_ssh_command.py`.

### Behavior

- Known-hosts file: `{settings.data_directory}/ssh/known_hosts` (directory mode `0o700`, file created empty with `0o600` if missing).
- SSH options: `IdentitiesOnly=yes`, `StrictHostKeyChecking=accept-new`, `UserKnownHostsFile=<path>`. Never `/dev/null`. Never `StrictHostKeyChecking=no`.
- Quote both the identity file and known-hosts path (today `auth.py` does not quote the key path).

### Code after — `backend/services/git/ssh_command.py` (new, entire file)

```python
from __future__ import annotations

from pathlib import Path

from core.config import settings

_KNOWN_HOSTS_REL = Path("ssh") / "known_hosts"


def git_known_hosts_path() -> Path:
    directory = settings.data_directory / "ssh"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = settings.data_directory / _KNOWN_HOSTS_REL
    if not path.exists():
        path.touch(mode=0o600)
    return path


def build_git_ssh_command(ssh_key_path: str) -> str:
    known_hosts = git_known_hosts_path()
    return (
        f'ssh -i "{ssh_key_path}" -o IdentitiesOnly=yes '
        f'-o StrictHostKeyChecking=accept-new '
        f'-o UserKnownHostsFile="{known_hosts}"'
    )
```

### Code before — `backend/services/git/connection.py` ~282–285

```python
            env["GIT_SSH_COMMAND"] = (
                f'ssh -i "{ssh_key_path}" '
                "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
            )
```

### Code after

```python
            from services.git.ssh_command import build_git_ssh_command

            env["GIT_SSH_COMMAND"] = build_git_ssh_command(ssh_key_path)
```

### Code before — `backend/services/git/auth.py` ~286–288

```python
                os.environ["GIT_SSH_COMMAND"] = (
                    f"ssh -i {ssh_key_path} -o StrictHostKeyChecking=no -o IdentitiesOnly=yes"
                )
```

### Code after

```python
                from services.git.ssh_command import build_git_ssh_command

                os.environ["GIT_SSH_COMMAND"] = build_git_ssh_command(ssh_key_path)
```

Put the import at module top in both files, not inline.

### Tests (`test_git_ssh_command.py`)

- `build_git_ssh_command("/tmp/id_rsa")` contains `StrictHostKeyChecking=accept-new` and `UserKnownHostsFile=` and does **not** contain `StrictHostKeyChecking=no` or `/dev/null`.
- Patch `settings.data_directory` to a temp dir; after the call, `data_directory/ssh/known_hosts` exists.
- Grep guard in the same test file: read `connection.py` and `auth.py` as text and `assert "StrictHostKeyChecking=no" not in source`.

### Tests to run

`tests/unit/test_git_ssh_command.py tests/unit/test_git_service_url_validation.py`

---

## H2 — SSH git remote IP policy

**Files:** `backend/core/safe_urls.py`; `backend/tests/unit/test_safe_urls.py`; `backend/tests/unit/test_production_hardening.py` (`TestR3GitRemoteUrl.test_accepts_scp_like`); `backend/tests/unit/test_source_connection_tests.py` (the two SSH URL assertions); `backend/tests/unit/test_git_service_url_validation.py` (comment that ssh skips DNS — update).

### Behavior

HTTPS already calls `_assert_ip_allowed` / `_assert_resolved_hosts_allowed`. SSH, `git+ssh`, and scp-like URLs must do the same. RFC1918 remains **allowed** (on-prem git). Loopback / link-local / multicast / unspecified / `metadata.google.internal` remain **blocked** (loopback still gated by `allow_loopback_source_urls`).

Extract a helper used by all three git URL shapes:

```python
def _assert_git_host_allowed(host: str, *, resolve_dns: bool) -> None:
    normalized = (host or "").strip().lower()
    if not normalized:
        raise UnsafeURLError("URL host is required")
    if normalized in _BLOCKED_HOSTNAMES:
        raise UnsafeURLError(f"URL host is not allowed: {normalized}")
    try:
        literal_ip = ipaddress.ip_address(normalized)
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        _assert_ip_allowed(literal_ip)
    if resolve_dns:
        _assert_resolved_hosts_allowed(normalized)
```

### Code before — `validate_git_remote_url` ssh / scp branches (`core/safe_urls.py` 79–99)

```python
    if scheme in ("ssh", "git+ssh"):
        host = (parsed.hostname or "").strip()
        if not host:
            raise UnsafeURLError("URL host is required")
        return raw

    # ... http development branch unchanged ...

    if not raw.startswith(("/", "\\")) and _SCP_LIKE_PATTERN.match(raw):
        host_part = raw.split(":", 1)[0]
        host = host_part.split("@", 1)[-1] if "@" in host_part else host_part
        if not host:
            raise UnsafeURLError("URL host is required")
        return raw
```

### Code after

```python
    if scheme in ("ssh", "git+ssh"):
        host = (parsed.hostname or "").strip()
        _assert_git_host_allowed(host, resolve_dns=resolve_dns)
        return raw

    # http development branch: also call _assert_git_host_allowed(host, resolve_dns=resolve_dns)
    # before `return raw.rstrip("/")`

    if not raw.startswith(("/", "\\")) and _SCP_LIKE_PATTERN.match(raw):
        host_part = raw.split(":", 1)[0]
        host = host_part.split("@", 1)[-1] if "@" in host_part else host_part
        _assert_git_host_allowed(host, resolve_dns=resolve_dns)
        return raw
```

Development `http://` git remotes currently skip DNS/IP checks. Apply `_assert_git_host_allowed` there too (same helper).

### Tests to add in `test_safe_urls.py`

Patch `socket.getaddrinfo` like existing tests.

| Input | `resolve_dns` | Expect |
|-------|---------------|--------|
| `ssh://git@git.example.com/org/repo.git` with DNS `203.0.113.10` | True | returns input |
| `ssh://git@169.254.169.254/org/repo.git` | False | `UnsafeURLError` |
| `ssh://git@127.0.0.1/org/repo.git` with `allow_loopback_source_urls=False` | False | `UnsafeURLError` |
| `git@169.254.169.254:org/repo.git` | False | `UnsafeURLError` |
| `git@git.example.com:org/repo.git` with DNS `10.0.0.5` | True | returns input (RFC1918 allowed) |
| `ssh://git@metadata.google.internal/org/repo.git` | False | `UnsafeURLError` |

### Tests to update

Every existing `validate_git_remote_url("git@git.example.com:...")` and `ssh://git@...` call must patch `socket.getaddrinfo` to a public or RFC1918 address, or it will do real DNS. Files:

- `test_production_hardening.py` `test_accepts_scp_like`
- `test_source_connection_tests.py` scp-like and `ssh://` cases
- `test_git_service_url_validation.py` ssh case — delete the comment “skips DNS resolution”; add a `getaddrinfo` patch

### Tests to run

`tests/unit/test_safe_urls.py tests/unit/test_production_hardening.py tests/unit/test_source_connection_tests.py tests/unit/test_git_service_url_validation.py`

---

## H3 — RBAC anti-elevation

**Files:** `backend/services/auth/rbac_service.py`; `backend/routers/rbac/user_access.py`; `backend/routers/rbac/roles.py`; `backend/tests/unit/test_rbac_service.py`; add `backend/tests/unit/test_rbac_elevation.py`.

No new permission catalog entries. System-role mutations require the actor to hold the **`admin` role** (`RBACService.has_role`). `require_role("admin")` already exists in `core/auth.py`.

### Rules (implement in `RBACService`, not only in the router)

1. **Assigning a role whose `is_system` is True** (today `admin` and `viewer`) to any user: actor must have role `admin`.
2. **Assigning any permission to a system role**, or **removing a permission from a system role**: actor must have role `admin`.
3. **Creating a role with `is_system=True`**: actor must have role `admin`.
4. `admin_reseed_rbac` / `assign_role_to_user_by_name` used at startup stay unchanged (no actor). Add an optional `actor_user_id: int | None = None` to the mutating methods; when `None`, skip the elevation check (seed/lifespan only).

Raise `AccessDeniedError` (created in **H4** — if you implement H3 first, raise a local `PermissionError("Admin role required to modify system roles")` and in H4 switch it to `AccessDeniedError` with detail `"Admin role required to modify system roles"`). **Preferred:** implement the exception types from H4 first if you touch both in one sitting; otherwise use `PermissionError` and map it in the two routers as 403 until H4 lands.

This plan assumes **H4 types exist**. If coding H3 in isolation, create only `AccessDeniedError` in `backend/core/domain_exceptions.py` (the rest of H4 can fill the file).

### Code after — add to `RBACService`

```python
from core.domain_exceptions import AccessDeniedError

def _require_admin_actor(self, actor_user_id: int | None) -> None:
    if actor_user_id is None:
        return
    if not self.has_role(actor_user_id, "admin"):
        raise AccessDeniedError("Admin role required to modify system roles")

def assign_role_to_user(self, user_id: int, role_id: int, *, actor_user_id: int | None = None):
    role = self.get_role(role_id)
    if role is not None and role.is_system:
        self._require_admin_actor(actor_user_id)
    return self._repo.assign_role_to_user(user_id, role_id)

def assign_permission_to_role(
    self, role_id: int, permission_id: int, granted: bool = True, *, actor_user_id: int | None = None
):
    role = self.get_role(role_id)
    if role is not None and role.is_system:
        self._require_admin_actor(actor_user_id)
    return self._repo.assign_permission_to_role(role_id, permission_id, granted)

def remove_permission_from_role(
    self, role_id: int, permission_id: int, *, actor_user_id: int | None = None
) -> bool:
    role = self.get_role(role_id)
    if role is not None and role.is_system:
        self._require_admin_actor(actor_user_id)
    return self._repo.remove_permission_from_role(role_id, permission_id)

def create_role(
    self,
    name: str,
    description: str | None = None,
    is_system: bool = False,
    *,
    actor_user_id: int | None = None,
):
    if is_system:
        self._require_admin_actor(actor_user_id)
    return self._repo.create_role(name, description, is_system)
```

Keep `assign_role_to_user_by_name` calling `assign_role_to_user` **without** `actor_user_id` so lifespan seed still works.

### Code before — `routers/rbac/user_access.py` `assign_user_role`

```python
    service.assign_role_to_user(user_id, payload.role_id)
```

### Code after

Add `current_user: User = Depends(get_current_user)` to the handler (already imported).

```python
    service.assign_role_to_user(user_id, payload.role_id, actor_user_id=current_user.id)
```

Catch `AccessDeniedError` → `HTTPException(403, detail=str(exc))` until H4’s global handler exists; after H4, delete the local catch.

### Code before — `routers/rbac/roles.py`

`create_role(...)`, `assign_role_permission(...)`, `remove_role_permission(...)` call the service with no actor.

### Code after

Each of those three handlers already can take `current_user: User = Depends(get_current_user)`. Pass `actor_user_id=current_user.id` into `create_role`, `assign_permission_to_role`, and `remove_permission_from_role`.

### Tests (`test_rbac_elevation.py`)

Use the same in-memory SQLite pattern as `test_rbac_service.py`.

1. Non-admin user with `users:write` equivalent is irrelevant at service layer: call `assign_role_to_user(target, admin_role_id, actor_user_id=non_admin.id)` → `AccessDeniedError`.
2. Admin actor can assign `admin` to another user.
3. Non-admin actor cannot `assign_permission_to_role` on the admin role.
4. `assign_role_to_user_by_name(admin_user.id, "admin")` with no actor still succeeds (seed path).
5. `create_role("x", is_system=True, actor_user_id=non_admin.id)` → `AccessDeniedError`.

Existing `test_rbac_service.py` calls `assign_role_to_user(self.user.id, role.id)` with two positional args — still valid because `actor_user_id` defaults to `None`.

### Tests to run

`tests/unit/test_rbac_service.py tests/unit/test_rbac_seed.py tests/unit/test_rbac_elevation.py`

---

## H4 — Domain exceptions; no `HTTPException` in services

This is the largest item. Do it as one mechanical pass after creating the types and the FastAPI handler.

### New file `backend/core/domain_exceptions.py` (entire file)

```python
from __future__ import annotations


class DomainError(Exception):
    """Business error mapped to a 4xx HTTP response by the FastAPI handler."""

    status_code: int = 400

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFoundError(DomainError):
    status_code = 404


class AccessDeniedError(DomainError):
    status_code = 403


class ConflictError(DomainError):
    status_code = 409


class ValidationFailedError(DomainError):
    status_code = 400
```

Do **not** add a 5xx domain exception. Unexpected failures stay as ordinary exceptions and are converted with `raise_internal_server_error` in routers **or** by the catch-all handler below.

### Register handler in `backend/main.py`

Add immediately after `app = FastAPI(...)`:

```python
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from core.domain_exceptions import DomainError
from core.safe_http_errors import INTERNAL_ERROR_MESSAGE, internal_error_detail

@app.exception_handler(DomainError)
async def domain_error_handler(_request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
```

Do **not** add a catch-all `Exception` handler (it would hide bugs and change 500 shape globally). Routers that currently `except Exception: raise_internal_server_error(...)` keep doing that.

Existing typed exceptions (`CredentialNotFoundError`, `TemplateNotFoundError`, `ISENotFoundError`, …) stay. Optionally subclass them from `NotFoundError` later; **do not** in this pass.

### Mechanical replacement in these files only

| File | Action |
|------|--------|
| `services/settings/settings_service.py` | Replace every `HTTPException` |
| `services/git/shared_utils.py` | Replace 404/400 `HTTPException`; keep `raise_internal_server_error` for open/clone failures |
| `services/git/csv_service.py` | Replace every `HTTPException` |
| `services/git/file_service.py` | Replace every `HTTPException` |
| `services/workflow/workflow_service.py` | Replace 400/403/404; **delete** the 500 `HTTPException` block (see below) |
| `services/execution/run_service.py` | Replace every `HTTPException` |
| `services/execution/schedule_service.py` | Replace every `HTTPException` |

Remove `from fastapi import HTTPException` and `from fastapi import status` from those files when unused. Import domain errors from `core.domain_exceptions`.

### Mapping table (apply exactly)

| Old | New |
|-----|-----|
| `HTTPException(status_code=404, detail=D)` or `HTTP_404_NOT_FOUND` | `NotFoundError(D)` |
| `HTTPException(..., HTTP_403_FORBIDDEN, detail=D)` or `status_code=403` | `AccessDeniedError(D)` |
| `HTTPException(..., HTTP_409_CONFLICT, detail=D)` | `ConflictError(D)` |
| `HTTPException(..., HTTP_400_BAD_REQUEST, detail=D)` or `status_code=400` | `ValidationFailedError(D)` |
| `HTTPException(..., 500, detail="Workflow created but could not be retrieved")` | See next subsection |

Keep `detail` strings **byte-for-byte** including f-strings, except H4 5xx and the M6 git bodies.

`settings_service.py` `detail=str(exc)` for validation → `ValidationFailedError(str(exc))`.

### `workflow_service.py` create path — code before

```python
            result = self.repo.get_by_id(workflow.id)
            if result is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Workflow created but could not be retrieved",
                )
            ...
        except HTTPException:
            raise
        except Exception:
            logger.info("Failed to create workflow name=%r user_id=%s", data.name, user_id, exc_info=True)
            raise
```

### Code after

```python
            result = self.repo.get_by_id(workflow.id)
            if result is None:
                logger.error(
                    "Workflow created but could not be retrieved id=%s user_id=%s",
                    workflow.id,
                    user_id,
                )
                raise RuntimeError("Workflow created but could not be retrieved")
            ...
        except DomainError:
            raise
        except Exception:
            logger.info("Failed to create workflow name=%r user_id=%s", data.name, user_id, exc_info=True)
            raise
```

**API contract change (intentional):** that failure becomes a sanitized `{message, error_id}` 500 from whatever router `except Exception` already calls `raise_internal_server_error`, or an unhandled 500 if the router does not catch it. Check `routers/workflows.py` create handler: if it does not wrap `create_workflow` in `except Exception`, add:

```python
    except DomainError:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to create workflow", exc)
```

Do the same for `update_workflow` / `delete_workflow` if they currently rely on FastAPI converting a bare `raise`.

Replace every `except HTTPException: raise` in these services with `except DomainError: raise`.

### `shared_utils.get_git_repo_by_id`

404/inactive → `NotFoundError` / `ValidationFailedError`. Leave `raise_internal_server_error` for clone failures (that helper is allowed to raise `HTTPException` because it is HTTP-facing; **after H5** move clone failures to `RuntimeError` + router `raise_internal_server_error`. For H4, leave `raise_internal_server_error` in `shared_utils.py` as the one service-layer exception to HTTP. If `scripts/check_http_500_leaks.py` only scans routers, this is fine.

### Tests that currently expect `HTTPException` from services

Change `from fastapi import HTTPException` / `pytest.raises(HTTPException)` / `assertRaises(HTTPException)` to the matching domain class, and assert `exc.detail` or `str(exc)` instead of `exc.status_code` **or** assert `exc.status_code` on the domain class (`NotFoundError.status_code == 404`).

Known files:

- `tests/unit/test_workflow_service_graph_validation.py`
- `tests/unit/test_run_service_delete.py`
- `tests/unit/test_run_service_approval.py`
- `tests/unit/test_run_service_run_inputs.py`

Search `backend/tests` for `HTTPException` imported alongside these services and update any remaining hits the same way.

Grep after the pass (must be empty except `shared_utils.py` if you left `raise_internal_server_error` there):

```
rg 'raise HTTPException' backend/services --glob '*.py'
```

Allowed leftover: none, if you also change `shared_utils` clone failure to `raise RuntimeError(...) from e` and let git routers catch it. **Do that.** Then `shared_utils.py` has zero FastAPI imports.

`get_git_repo_by_id` clone failure after H4:

```python
        except Exception as e:
            logger.exception("Failed to open/clone Git repository %s", repository["name"])
            raise RuntimeError(
                f"Failed to open/clone Git repository {repository['name']}"
            ) from e
```

Git routers that call `get_git_repo_by_id` already have `except Exception: raise_internal_server_error(...)`.

### Tests to run

`tests/unit/test_workflow_service_graph_validation.py tests/unit/test_run_service_delete.py tests/unit/test_run_service_approval.py tests/unit/test_run_service_run_inputs.py tests/unit/test_production_hardening.py`

Plus any test that imported `SettingsService` and expected `HTTPException`.

---

## H5 — Thin routers

Do **after H4** so new service methods raise domain errors.

### H5a — Git operations orchestration

**Files:** `backend/services/git/operations.py`; `backend/routers/git/operations.py`.

Move `_fail_sync_with_error_id`, sync status updates, cache invalidation, and `/info` git-stat collection into `GitOperationsService`.

Add these methods to `GitOperationsService` (use `git_repo_manager` until M5 replaces it):

```python
def get_status_payload(self, repo_id: int) -> dict:
    repository = git_repo_manager.get_repository(repo_id)
    if not repository:
        raise NotFoundError("Repository not found")
    status_info = self.get_repository_status(repository, repo_id)
    return {"success": True, "data": status_info}

def sync_and_record(self, repo_id: int, git_cache_service) -> dict:
    ...  # body of current router sync_repository try-block
    # on failure call self._fail_sync(repo_id, message, exc=None) which
    # updates sync_status to error:{uuid}, logs, then raises RuntimeError
    # Routers catch RuntimeError with raise_internal_server_error.

def remove_and_sync_and_record(self, repo_id: int, git_cache_service) -> dict:
    ...  # same for remove_and_sync

def get_info_payload(self, repo_id: int) -> dict:
    ...  # body of current get_repository_info success path; 404 -> NotFoundError

def get_debug_payload(self, repo_id: int) -> dict:
    repo = get_git_repo_by_id(repo_id)
    return {"status": "success", "repo_path": repo.working_dir, "branch": repo.active_branch.name}
```

`_fail_sync` must **not** raise `HTTPException`. It updates DB then `raise RuntimeError(log_message)`.

#### Router after (pattern for every handler)

```python
@router.get("/status", dependencies=[Depends(require_permission("git.operations", "read"))])
async def get_repository_status(
    repo_id: int,
    current_user: dict = Depends(get_current_user),
    git_operations_service=Depends(get_git_operations_service),
):
    try:
        return git_operations_service.get_status_payload(repo_id)
    except DomainError:
        raise
    except Exception:
        error_id = str(uuid.uuid4())
        logger.error("Error getting repository status (error_id=%s)", error_id, exc_info=True, extra={"error_id": error_id})
        return {"success": False, "message": "Failed to get repository status", "error_id": error_id}
```

Keep the `/status` **non-raising** error envelope (`success: False`) — that is the current contract.

`/sync` and `/remove-and-sync` after:

```python
    try:
        return git_operations_service.sync_and_record(repo_id, git_cache_service)
    except DomainError:
        raise
    except Exception as e:
        raise_internal_server_error(logger, f"Error syncing repository {repo_id}", e)
```

`sync_and_record` itself must persist `error:{error_id}` **before** raising, using the same `error_id` the router puts in `internal_error_detail`. To keep correlation: have `sync_and_record` catch failure, write `error:{uuid}`, then raise `RuntimeError` with that uuid in `e.args`, **or** return a `SyncResult` and let the router call a small `record_sync_failure(repo_id, error_id)` — simplest:

```python
def record_sync_failure(self, repo_id: int, error_id: str) -> None:
    git_repo_manager.update_sync_status(repo_id, f"error:{error_id}")
```

Router:

```python
    try:
        repository = ...  # NO — that stays in service
        return git_operations_service.sync_and_record(repo_id, git_cache_service)
    except DomainError:
        raise
    except Exception as e:
        error_id = str(uuid.uuid4())
        git_operations_service.record_sync_failure(repo_id, error_id)
        logger.error("Error syncing repository %s (error_id=%s)", repo_id, error_id, exc_info=True)
        raise HTTPException(status_code=500, detail=internal_error_detail(error_id=error_id)) from e
```

Wait — that splits orchestration again. **Do this instead:** `sync_and_record` catches all exceptions internally, writes `error:{id}`, and raises `HTTPException` via `raise_internal_server_error`? That puts HTTP back in the service, which H4 forbids.

**Final contract for sync failure:**

```python
class SyncExecutionError(RuntimeError):
    def __init__(self, error_id: str, log_message: str) -> None:
        super().__init__(log_message)
        self.error_id = error_id
```

In `sync_and_record`:

```python
        git_repo_manager.update_sync_status(repo_id, "syncing")
        result = self.sync_repository(repository)
        if result.success:
            git_repo_manager.update_sync_status(repo_id, "synced")
            git_cache_service.invalidate_repo(repo_id)
            return {"success": True, "message": result.message, "repository_path": result.repository_path}
        error_id = str(uuid.uuid4())
        git_repo_manager.update_sync_status(repo_id, f"error:{error_id}")
        logger.error("Sync failed for repository %s: %s (error_id=%s)", repo_id, result.message, error_id)
        raise SyncExecutionError(error_id, result.message)
```

Router:

```python
    except SyncExecutionError as e:
        raise HTTPException(
            status_code=500,
            detail=internal_error_detail(error_id=e.error_id),
        ) from e
    except DomainError:
        raise
    except Exception as e:
        raise_internal_server_error(logger, f"Error syncing repository {repo_id}", e)
```

Mirror for `remove_and_sync_and_record`.

Delete `_fail_sync_with_error_id` from the router. Target router size: ~80 lines.

### H5b — Netmiko preview service

**New file:** `backend/services/network/netmiko/preview_service.py`  
**Edit:** `backend/routers/netmiko.py`

Move the bodies of `run_commands` and `get_configs` (everything after empty-command check) into:

```python
class NetmikoPreviewService:
    def __init__(self, credentials_service: CredentialsService) -> None:
        self._credentials = credentials_service

    async def run_commands(
        self, payload: NetmikoRunCommandsRequest, *, acting_user_id: int
    ) -> NetmikoRunCommandsResponse: ...

    async def get_configs(
        self, payload: NetmikoGetConfigsRequest, *, acting_user_id: int
    ) -> NetmikoGetConfigsResponse: ...
```

Copy the current router logic verbatim: `validate_netmiko_preview_host`, credential fetch, SSH type check, decrypt password, `DeviceSessionPool(max_workers=1, enabled=False)`, `NetmikoService`, response mapping. Replace router `HTTPException` with:

- empty commands → `ValidationFailedError("At least one non-empty command is required")` (move the empty check into the service too)
- `ValueError` from `validate_netmiko_preview_host` → `ValidationFailedError(str(exc))`
- missing credential → `NotFoundError(f"Credential {id} not found")`
- wrong type → `ValidationFailedError("Selected credential must be an SSH credential")`
- `CredentialNotFoundError` / `CredentialMissingFieldError` → re-raise (router already maps those) **or** translate to `NotFoundError` / `ValidationFailedError` in the service so the router has one path

Keep mapping `CredentialNotFoundError` in the router as today if the service still uses `CredentialsService.get_credential_by_id` which returns `None` rather than raising.

Router after:

```python
def _preview_service(
    credentials_service: CredentialsService = Depends(_credentials_service),
) -> NetmikoPreviewService:
    return NetmikoPreviewService(credentials_service)

@router.post("/run-commands", response_model=NetmikoRunCommandsResponse)
async def run_commands(
    payload: NetmikoRunCommandsRequest,
    current_user: User = Depends(get_current_user),
    service: NetmikoPreviewService = Depends(_preview_service),
) -> NetmikoRunCommandsResponse:
    try:
        return await service.run_commands(payload, acting_user_id=current_user.id)
    except DomainError:
        raise
    except (CredentialNotFoundError, CredentialMissingFieldError) as exc:
        # keep existing status mapping from current router
        ...
    except NetmikoConnectionError as exc:
        raise_internal_server_error(...)  # same as current
```

Copy the existing except branches from `routers/netmiko.py` unchanged except `HTTPException` for validation now comes from `DomainError`.

### H5c — Nautobot ops: test-connection + inventory resolve

**Files:** `backend/services/sources/nautobot/source_service.py` (or a new `ops_service.py` next to it); `backend/routers/sources/nautobot/ops.py`.

**1. Test connection** — add `NautobotSourceService.test_saved_or_adhoc_connection` **or** a module-level function in `services/sources/nautobot/connection.py`:

```python
async def test_nautobot_connection(request: NautobotTestConnectionRequest, db: Session) -> NautobotTestConnectionResponse:
    # move lines 77–123 of ops.py here unchanged, except HTTPException -> domain errors / raise_internal_server_error stays in router
```

The current handler catches exceptions and uses `raise_internal_server_error`. Service should raise `NautobotAPIError` / `NautobotValidationError` (already exist). Router keeps those mappings.

**2. Inventory resolve** — add to `NautobotSourceService`:

```python
async def resolve_saved_inventory_ids(self, inventory: dict, inventory_id: int) -> dict:
    # body of resolve_inventory_to_devices from "if inventory_type == static" through the return dicts
    # raise NotFoundError if called with inventory is None — caller still loads inventory

async def resolve_saved_inventory_detailed(self, inventory: dict, inventory_id: int) -> dict:
    # body of resolve_inventory_to_devices_detailed device loop

async def resolve_saved_inventory_devices(self, inventory: dict) -> InventoryPreviewResponse:
    # body of get_inventory_devices
```

Router after (example):

```python
        inventory = persistence.get_inventory(inventory_id, username=current_user.username)
        if not inventory:
            raise NotFoundError(f"Inventory with ID {inventory_id} not found")
        source_service = _build_source_service(credentials, persistence)
        return await source_service.resolve_saved_inventory_ids(inventory, inventory_id)
```

`PermissionError` from `get_inventory` → `AccessDeniedError(str(exc))` in the router (one line) or translate inside persistence later. Keep router catch of `PermissionError` if you do not change persistence.

Leave `get_all_groups`, `preview_inventory`, `search_devices`, etc. as one-liners that already delegate — they are already thin enough.

### H5d — ISE ops

`_resolve_credentials` / `_resolve_device_service` / `_resolve_group_service` stay in the router (DI wiring). Do **not** move every CRUD one-liner.

Extract only `test_connection` (lines 282–318) into `ISESourceConfigService.test_connection(source_id) -> ISETestConnectionResponse` if that method does more than `resolve_credentials` + client call. Read the current handler: if it is already `credentials = _resolve...; await ise.test...; return ISETestConnectionResponse(...)`, moving it is optional. **Required:** delete duplicated try/except that interpolates `str(exc)` into 5xx — those paths must call `raise_internal_server_error` (they likely already do). If any ISE ops handler still does `detail=str(e)` for 5xx, replace it.

If a handler is >40 lines of branching, move that branch into `services/ise/network_device_service.py` or `network_device_group_service.py`. Do not create a new 500-line `ise/ops_service.py` that mirrors the router.

### H5e — Git source ops

`routers/sources/git/ops.py` handlers that call `SettingsService.get_source_config` then `git_source_service.*` should become:

```python
# in git_source_service.py
def test_connection_from_request(self, request, db) -> dict:
    ...
```

Move credential/config assembly out of the router for `test_connection`, `preview_git_devices`, `preview_git_content_search`, `pull_git_source`, `remove_and_clone_git_source`. Router becomes: permission, `Depends`, `return await service.method(request)`.

### H5f — System router

**New:** `backend/services/system/system_service.py`

```python
class SystemService:
    def schema_status(self) -> SchemaStatusResponse:
        return SchemaManager().get_schema_status()

    def migrate_schema(self, *, force: bool) -> SchemaMigrationResponse:
        return SchemaManager().perform_migration(force=force)

    def reseed_rbac(self, db: Session, *, remove_existing: bool) -> RbacSeedResponse:
        result = admin_reseed_rbac(db, remove_existing=remove_existing)
        return RbacSeedResponse(...)  # same fields as current router
```

Router becomes three one-liners + existing `require_dev_tools` / `require_permission` dependencies.

### Tests to run

Existing git/netmiko/nautobot/ise/system unit tests. Add none unless a moved function is untested; then add a service-level test that 404s with `NotFoundError`.

---

## M1 — Refuse `ENABLE_DEV_TOOLS` outside development

**Files:** `backend/core/production_guards.py`; `backend/core/config.py`; `backend/tests/unit/test_production_hardening.py`.

### Code before — `validate_non_development_secrets` signature

```python
def validate_non_development_secrets(
    *,
    environment: str,
    secret_key: str,
    initial_password: str,
    credential_encryption_key: str,
    database_password: str,
) -> None:
```

### Code after

Add `enable_dev_tools: bool` and `redis_password: str` (redis used in **M7** — add both parameters in this edit so `config.py` is touched once).

```python
def validate_non_development_secrets(
    *,
    environment: str,
    secret_key: str,
    initial_password: str,
    credential_encryption_key: str,
    database_password: str,
    enable_dev_tools: bool = False,
    redis_password: str = "",
    allow_netmiko_arbitrary_hosts: bool = False,
) -> None:
    if environment == "development":
        return
    # existing checks unchanged ...
    if enable_dev_tools:
        raise RuntimeError("ENABLE_DEV_TOOLS must not be set outside development")
    if not redis_password.strip():
        raise RuntimeError("MANUS_REDIS_PASSWORD must be configured outside development")
    if allow_netmiko_arbitrary_hosts:
        raise RuntimeError("ALLOW_NETMIKO_ARBITRARY_HOSTS must not be enabled outside development")
```

`allow_netmiko_arbitrary_hosts` is **M11**; include it here so production startup has one guard function.

### Code after — `core/config.py` call site (~119)

```python
        from core.dev_tools import dev_tools_enabled

        validate_non_development_secrets(
            environment=self.environment,
            secret_key=self.secret_key,
            initial_password=self.initial_password,
            credential_encryption_key=self.credential_encryption_key,
            database_password=self.database_password,
            enable_dev_tools=dev_tools_enabled(),
            redis_password=self.redis_password,
            allow_netmiko_arbitrary_hosts=self.allow_netmiko_arbitrary_hosts,
        )
```

Call this **after** `self.allow_netmiko_arbitrary_hosts` is assigned (it already is, just above the current call). `dev_tools_enabled()` reads the env var; do not import `dev_tools` at module top of `production_guards.py` (keeps that module pure).

### Tests — extend `TestR2ProductionGuards`

- Production + `enable_dev_tools=True` → `RuntimeError` matching `ENABLE_DEV_TOOLS`.
- Production + `redis_password=""` → `RuntimeError` matching `MANUS_REDIS_PASSWORD`.
- Production + `allow_netmiko_arbitrary_hosts=True` → `RuntimeError` matching `ALLOW_NETMIKO_ARBITRARY_HOSTS`.
- Update `test_production_accepts_distinct_strong_secrets` to pass `redis_password="strong-redis"`.
- Development still allows `enable_dev_tools=True`, empty redis password, and arbitrary netmiko hosts.

Every existing `validate_non_development_secrets(...)` call in that class must pass the new kwargs or rely on defaults: **defaults are unsafe for the new checks** (`enable_dev_tools=False`, `redis_password=""`). Production tests that currently succeed will **fail** on empty redis password. Update all production-success cases to `redis_password="strong-redis"`. Production **rejection** tests (weak secret key, etc.) can keep default `redis_password=""` — they raise earlier on the original check. Order the new checks **after** existing ones so existing rejection tests stay stable.

### Tests to run

`tests/unit/test_production_hardening.py`

---

## M2 — Never relax OIDC redirect validation

**Files:** `backend/core/oidc_redirect.py`; `backend/routers/oidc.py`; `backend/tests/unit/test_oidc_redirect.py`.

### Code before — `validate_oidc_redirect_uri`

```python
    if parsed.fragment:
        raise ValueError("redirect_uri must not contain a fragment")

    if dev_tools:
        return raw

    normalized_allowlist = ...
```

### Code after

Delete the `dev_tools` early-return. Keep the `dev_tools` parameter so callers do not break, but it must have **no effect**. Add a comment: `dev_tools is accepted for call-site compatibility and ignored.`

Delete `relax_redirect` from `_build_login_response` **or** stop passing `dev_tools=relax_redirect`. Simplest: in `_build_login_response`, always call `validate_oidc_redirect_uri(..., dev_tools=False)`.

### Code before — `initiate_test_login`

```python
    return await _build_login_response(
        ...
        relax_redirect=True,
    )
```

### Code after

```python
    return await _build_login_response(
        ...
        relax_redirect=False,
    )
```

Then delete the `relax_redirect` parameter from `_build_login_response` entirely if nothing else passes it.

Test-login remains gated by `dev_tools_enabled()` 404. Redirects must still be allow-listed (production) or localhost + `_DEV_PATHS` (development). `/login/oidc-test-callback` is already in `_DEV_PATHS`, so development test-login keeps working.

### Tests

Replace `test_dev_tools_skips_allowlist` with:

```python
    def test_dev_tools_does_not_skip_allowlist(self) -> None:
        with self.assertRaises(ValueError):
            validate_oidc_redirect_uri(
                "https://evil.example/callback",
                allowlist=[],
                environment="production",
                dev_tools=True,
            )
```

Keep `test_dev_tools_still_requires_http_scheme`. Rename if you drop the parameter.

### Tests to run

`tests/unit/test_oidc_redirect.py tests/unit/test_oidc_service.py`

---

## M3 — Dashboard permissions

**Files:** `backend/routers/dashboard.py`.

No new RBAC catalog entries. Reuse existing permissions.

| Route | Permission |
|-------|------------|
| `GET /dashboard/layout`, `PUT /dashboard/layout` | none beyond `get_current_user` (user’s own preference) |
| `GET /dashboard/schedules` | `workflows:read` |
| `GET /dashboard/recent-runs` | `workflow_runs:read` |
| `GET /dashboard/notifications` | `workflow_runs:read` |

### Code before

```python
router = APIRouter(
    prefix="/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(get_current_user)],
)
```

Handlers have no extra `require_permission`.

### Code after

Keep router-level `Depends(get_current_user)`. Add per-route:

```python
@router.get(
    "/schedules",
    response_model=DashboardScheduleListResponse,
    dependencies=[Depends(require_permission("workflows", "read"))],
)
async def get_dashboard_schedules(...):
    ...

@router.get(
    "/recent-runs",
    ...
    dependencies=[Depends(require_permission("workflow_runs", "read"))],
)
...

@router.get(
    "/notifications",
    ...
    dependencies=[Depends(require_permission("workflow_runs", "read"))],
)
```

Import `require_permission` from `core.auth`.

Visibility scoping in repositories stays as-is.

### Tests

If no dashboard router tests exist, add `backend/tests/unit/test_dashboard_router_permissions.py` using the same FastAPI `dependency_overrides` pattern as `test_production_hardening.py` `test_migrate_schema_returns_404_when_dev_tools_disabled`: override `get_current_user`, override `require_permission` is harder because it is a factory.

Simpler: a unit test is optional. Manual check: viewer role already gets all `read` actions via seed, so viewers still load the dashboard. Users with no `workflow_runs:read` get 403 on those three GETs.

If you add a test, mount only `dashboard.router` on a `FastAPI()` app, override `get_db` and `get_current_user`, and call `require_permission` for real against a user without permissions → 403.

### Tests to run

`tests/unit/test_rbac_seed.py` plus any new dashboard test.

---

## M4 — Plugin config via `PluginRegistryService`

**Files:** `backend/models/plugins.py`; `backend/services/plugin_registry/plugin_registry_service.py`; `backend/routers/workflow_steps.py`; `backend/main.py` (no change if service already on `app.state`); add tests in `backend/tests/unit/test_plugin_registry_capabilities.py` or a new `test_plugin_config_loader.py`.

### New model in `models/plugins.py`

```python
class PluginConfigResponse(BaseModel):
    plugin_id: str
    config: dict[str, Any]
```

Delete the duplicate class from the router.

### Add to `PluginRegistryService`

Root for configs is the parent of the registry file’s directory name: today `settings.plugins_file` is `backend/workflow_steps/registry.yaml`, so configs live in `plugins_file.parent / plugin.directory / "config.py"`.

```python
import importlib.util
import logging
from typing import Any

logger = logging.getLogger(__name__)

def get_plugin_config(self, plugin_id: str) -> dict[str, Any]:
    plugin = self.get_plugin(plugin_id)
    if plugin is None:
        return None  # router raises 404

    config_path = self.repository.plugins_file.parent / plugin.directory / "config.py"
    if not config_path.is_file():
        return {}

    module_name = f"workflow_steps.{plugin.directory}.config"
    spec = importlib.util.spec_from_file_location(module_name, config_path)
    if spec is None or spec.loader is None:
        logger.warning("Cannot load config module for plugin '%s'", plugin_id)
        return {}

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    get_config = getattr(module, "get_config", None)
    if not callable(get_config):
        return {}
    try:
        cfg = get_config()
    except Exception:
        logger.exception("get_config() failed for plugin '%s'", plugin_id)
        return {}
    if not isinstance(cfg, dict):
        return {}
    return cfg
```

`get_plugin_config` returning `None` means unknown plugin; `{}` means no/invalid config.

### Router after

```python
from models.plugins import (
    PluginConfigResponse,
    PluginDefinition,
    PluginListResponse,
    PluginRegistryResponse,
)

@router.get("/{plugin_id}/get-config", response_model=PluginConfigResponse)
async def get_plugin_config(
    plugin_id: str,
    service: PluginRegistryService = Depends(get_plugin_service),
) -> PluginConfigResponse:
    plugin = service.get_plugin(plugin_id)
    if plugin is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin not found")
    cfg = service.get_plugin_config(plugin_id)
    return PluginConfigResponse(plugin_id=plugin_id, config=cfg or {})
```

Delete `_WORKFLOW_STEPS_ROOT`, `importlib`, and `Path` from the router.

### Tests

Load the real `registry.yaml` via `PluginRepository(settings.plugins_file)` (or the path used in existing plugin tests). `get_plugin_config("run-command")` (or any plugin that has `config.py`) returns a dict. `get_plugin_config("funnel")` returns `{}` (no config file). `get_plugin_config("does-not-exist")` — `get_plugin` is None; router 404.

### Tests to run

`tests/unit/test_plugin_registry_capabilities.py` plus the new test.

---

## M5 — Request-scoped Git DB sessions

**Files:** `backend/repositories/git/git_repository_repository.py`; `backend/services/git/repository_service.py`; `backend/services/git/shared_utils.py`; `backend/routers/git/repositories.py`; `backend/routers/git/operations.py`; `backend/dependencies.py`; `backend/service_factory.py`; callers of `git_repo_manager` listed below.

### Repository

```python
class GitRepositoryRepository(BaseRepository[GitRepository]):
    def __init__(self, db: Session | None = None):
        super().__init__(GitRepository)
        self._db = db

    def get_by_name(self, name: str, db: Session | None = None) -> GitRepository | None:
        with self._db_session(db or self._db) as s:
            ...
```

Pass `db or self._db` into every `_db_session(...)` in this class (`get_by_category`, `get_all_active`, `name_exists`, and inherited `create`/`update`/`delete`/`get_by_id`/`get_all` via overriding or by always passing `self._db`).

Inherited `BaseRepository.create` uses `_db_session(db)`. Easiest path: override nothing on BaseRepository; instead `GitRepositoryService` always passes `db=self._db` into every `self._repo.*(..., db=self._db)` call. Today `create_repository` calls `self._repo.create(...)` without `db`, which opens a new session.

**Required change in `GitRepositoryService`:**

```python
    def __init__(self, db: Session | None = None) -> None:
        self._db = db
        self._repo = GitRepositoryRepository(db)

    def create_repository(self, repo_data: dict[str, Any]) -> int:
        if self._repo.name_exists(repo_data["name"], db=self._db):
            ...
        new_repo = self._repo.create(db=self._db, name=..., ...)
```

Apply `db=self._db` to **every** `_repo` call in this file (`get_repository`, `get_repositories`, `update_repository`, `delete_repository`, `update_sync_status`, `health_check`).

When `db` is `None`, behavior stays self-managed (Hatchet/debug). HTTP request paths must pass the request session.

### Kill the module singleton for HTTP

**Before:** `git_repo_manager = GitRepositoryManager()` in `shared_utils.py`.

**After:**

```python
def get_git_repository_service(db: Session = Depends(get_db)) -> GitRepositoryService:
    return GitRepositoryService(db)
```

Put this in `backend/dependencies.py`. Delete `build_git_repository_service` from `service_factory.py` (unused). Delete `get_git_service` from `dependencies.py` (unused).

Replace HTTP usages:

| File | Change |
|------|--------|
| `routers/git/repositories.py` | `Depends(get_git_repository_service)` instead of `git_repo_manager` |
| `routers/git/operations.py` | inject service; `GitOperationsService` methods take `GitRepositoryService` **or** the operations service is constructed with it |

`GitOperationsService.__init__(self, repos: GitRepositoryService | None = None)` default `GitRepositoryService()` for tests; `dependencies.get_git_operations_service` becomes:

```python
def get_git_operations_service(
    repos: GitRepositoryService = Depends(get_git_repository_service),
):
    return GitOperationsService(repos)
```

`file_service.py`, `csv_service.py`, `debug_service.py` still import `git_repo_manager`. Change them to accept `GitRepositoryService` in `__init__` (default `GitRepositoryService()`). Wire FastAPI `Depends` in `routers/git/files.py` and `routers/git/debug.py` the same way.

Keep `shared_utils.git_repo_manager = GitRepositoryService()` **only** as a deprecated alias if a test imports it; prefer deleting it and fixing imports.

`get_git_repo_by_id(repo_id, repos: GitRepositoryService | None = None)` uses `repos or GitRepositoryService()`.

### Tests to run

Any `tests/unit/test_git_*` plus a quick import of `routers.git.repositories`.

---

## M6 — Sanitize git error bodies

Do together with H4 replacements in git services.

### `GitRepositoryService.health_check`

**Before:**

```python
        except Exception as e:
            logger.error("Health check failed: %s", e)
            return {"status": "error", "error": str(e), "database": "PostgreSQL"}
```

**After:**

```python
        except Exception:
            logger.exception("Health check failed")
            return {"status": "error", "error": "unavailable", "database": "PostgreSQL"}
```

### `GitConnectionService` exception handler (~152–158)

**Before:** `message=f"Git connection test error: {str(e)}"` and `details={"error": str(e)}`.

**After:**

```python
        except Exception:
            logger.exception("Error testing git connection")
            return GitConnectionTestResponse(
                success=False,
                message="Git connection test failed",
                details={},
            )
```

### Failed clone stderr (~328–335)

**Before:** `details={"error": safe_stderr, "return_code": result.returncode}` returned to the client.

**After:** log `safe_stderr` at warning (already does). Client payload:

```python
            return GitConnectionTestResponse(
                success=False,
                message="Git connection failed",
                details={"return_code": result.returncode},
            )
```

Do not include stderr in `details`.

### `file_service.py` 4xx that interpolate `str(e)`

**Before:**

```python
detail=f"Git repository not found or commit not found: {str(e)}"
detail=f"YAML parse error: {str(e)}"
```

**After:**

```python
raise NotFoundError("Git repository or commit not found")
raise ValidationFailedError("YAML parse error")
```

Log `str(e)` with `logger.info` / `logger.warning` and `exc_info=True` before raising.

### Tests to run

Git connection tests, file service tests if any; `test_source_connection_tests.py`.

---

## M7 — Login rate limiter fail-closed outside development

**Files:** `backend/services/auth/login_rate_limiter.py`; `backend/dependencies.py` (where limiter is built); `backend/tests/unit/test_login_rate_limiter.py`. Redis password is already in **M1**.

### `LoginRateLimiter.__init__`

```python
    def __init__(self, redis_url: str, key_prefix: str = "manus-login-rl", *, fail_closed: bool = False):
        self._fail_closed = fail_closed
        ...
```

### `check` after

```python
    def check(self, key: str) -> None:
        try:
            self._check_redis(key)
        except redis.RedisError:
            if self._fail_closed:
                logger.error("Login rate limiter: Redis unavailable, failing closed")
                raise RateLimitExceededError(key)
            logger.warning(
                "Login rate limiter: Redis unavailable, using in-process fallback for this check"
            )
            self._check_fallback(key)
```

### Wire-up

Find `get_login_rate_limiter` in `dependencies.py`. Pass `fail_closed=settings.environment != "development"`.

### Tests

- Existing fallback test stays valid when `fail_closed=False` (default).
- New test: `LoginRateLimiter(..., fail_closed=True)` with `pipeline.side_effect = redis.ConnectionError("down")` → first `check` raises `RateLimitExceededError`.

### Tests to run

`tests/unit/test_login_rate_limiter.py`

---

## M8 — Harden `TRUSTED_PROXY_IPS`

**Files:** `backend/core/config.py`.

### After building `self.trusted_proxy_ips`

Validate every entry is a unicast IP (no CIDR in this pass — current parser is CSV of hosts). Reject `0.0.0.0`, `::`, `::0`.

```python
        self.trusted_proxy_ips = set(self._get_csv("TRUSTED_PROXY_IPS", ""))
        self._validate_trusted_proxy_ips()
```

```python
    def _validate_trusted_proxy_ips(self) -> None:
        from ipaddress import ip_address

        cleaned: set[str] = set()
        for raw in self.trusted_proxy_ips:
            try:
                parsed = ip_address(raw)
            except ValueError as exc:
                raise RuntimeError(f"TRUSTED_PROXY_IPS contains an invalid IP: {raw}") from exc
            if parsed.is_unspecified:
                raise RuntimeError(f"TRUSTED_PROXY_IPS must not include unspecified address {raw}")
            cleaned.add(str(parsed))
        self.trusted_proxy_ips = cleaned
```

Do **not** fail if the set is empty (direct connections remain valid). `_get_client_host` in `routers/auth.py` is unchanged.

Add a unit test in `test_production_hardening.py` that constructs the validator by calling a extracted function if `Settings()` is too heavy. Prefer extracting `_validate_trusted_proxy_ips` as a module-level function `validate_trusted_proxy_ips(values: set[str]) -> set[str]` in `core/config.py` or `core/safe_hosts.py` so tests do not instantiate full `Settings`.

### Tests to run

New tests plus `tests/unit/test_production_hardening.py`.

---

## M9 — Redact secret-named keys in run output

**Files:** `backend/services/workflow_context/secret_fields.py`; `backend/tests/unit/test_secret_fields.py`.

Existing path and sealed-envelope redaction stay. Add a third mechanism: dict keys whose lowercase name is in a frozenset, or ends with `_password` / `_secret` / `_token`.

```python
_SECRET_KEY_NAMES = frozenset({
    "password",
    "secret",
    "token",
    "community",
    "shared_secret",
    "sharedsecret",
    "passphrase",
    "api_key",
    "apikey",
    "enable_secret",
    "snmp_community",
})

def _key_is_secret_name(key: str) -> bool:
    lowered = key.replace("-", "_").lower()
    if lowered in _SECRET_KEY_NAMES:
        return True
    return lowered.endswith(("_password", "_secret", "_token", "_passphrase"))
```

In `_redact_inplace`, when iterating a dict, if `_key_is_secret_name(key)` and the value is a `str`, set `node[key] = REDACTED_PLACEHOLDER`. Still recurse into dict/list values so nested bags work. Do **not** redact non-str values (bools, ints) so `enableKeyWrap: True` stays. `sharedSecret` becomes `sharedsecret` after lowercasing and matches the set.

`ise.tacacsSettings.sharedSecret` is already covered by `SECRET_BAG_PATHS`; the new rule also redacts `{ "password": "x" }` anywhere, including command-output JSON.

### Tests to add

```python
    def test_redacts_password_key_outside_bags(self) -> None:
        data = {"output": {"password": "clear", "hostname": "r1"}}
        redacted = redact_secrets_in_data(data)
        self.assertEqual(redacted["output"]["password"], REDACTED_PLACEHOLDER)
        self.assertEqual(redacted["output"]["hostname"], "r1")
```

Existing tests must still pass (`enableKeyWrap` not redacted).

### Tests to run

`tests/unit/test_secret_fields.py`

---

## M10 — TLS-disable warnings; pyATS default verify True

**Accepted:** Nautobot/ISE may still use `verify_ssl=False` (already log WARNING).

### Mattermost — `services/mattermost/client.py`

In the request helper that already branches on `verify_ssl` (the method that takes `verify_ssl: bool`, ~196), if not `verify_ssl`:

```python
            logger.warning(
                "Mattermost request with verify_ssl=False url_host=%s",
                urlparse(url).hostname,
            )
```

Import `urlparse` if missing.

### pyATS — `services/pyats/client.py`

Same WARNING on the request helper:

```python
                "pyATS shim request with verify_ssl=False url_host=%s",
```

### pyATS default True

`services/pyats/credentials.py`: `verify_ssl: bool = True` (currently `False`).  
`services/pyats/source_config_service.py`: `verify_ssl: bool = True` on create; `value.get("verify_ssl", True)` on resolve (currently `False`).

Update pyATS unit tests that assume default False.

### Git HTTPS — `services/git/env.py`

```python
        if not repository.get("verify_ssl", True):
            logger.warning("Git SSL verification disabled for repository url_host=%s", ...)
            os.environ["GIT_SSL_NO_VERIFY"] = "1"
```

Need a logger in `env.py`. Host: parse `repository.get("url")` with `urlparse`; if parse fails, log `"unknown"`.

### Tests to run

pyATS source config tests, mattermost tests if any, `tests/unit/test_git_*` that use `verify_ssl=False`.

---

## M11 — Netmiko arbitrary hosts outside development

Implemented in **M1** via `allow_netmiko_arbitrary_hosts` on `validate_non_development_secrets`. No further router change. `core/safe_hosts.py` stays as-is (development + flag still allow RFC1918).

Confirm `core/config.py` assigns `allow_netmiko_arbitrary_hosts` **before** the guard call (already true).

---

## M12 — Template credential visibility in the service

**Files:** `backend/services/templates/templates_service.py`; `backend/routers/templates.py`; `backend/services/templates/exceptions.py`.

### New exception

```python
class TemplateCredentialNotFoundError(TemplateError):
    def __init__(self, credential_id: int) -> None:
        super().__init__(f"Credential {credential_id} not found")
        self.credential_id = credential_id
```

### Move `_assert_credential_visible` into `TemplatesService`

```python
    def _assert_credential_visible(self, credential_id: int | None, *, acting_user_id: int) -> None:
        if credential_id is None:
            return
        credential = CredentialsService(self.db).get_credential_by_id(
            credential_id, acting_user_id=acting_user_id
        )
        if credential is None:
            raise TemplateCredentialNotFoundError(credential_id)
```

Call it at the start of `create_template` / `update_template` (whatever methods the router calls after `_assert_credential_visible`). Pass `acting_user_id`.

### Router after

Delete `_assert_credential_visible`. Map in create/update:

```python
    except TemplateCredentialNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
```

(Same pattern as `TemplateNotFoundError` already in that file.)

### Tests to run

Template unit tests if present; otherwise add one service test: private credential of user 2 is not visible to user 1 → `TemplateCredentialNotFoundError`.

---

## Verification checklist (end)

From `backend/`:

```
../.venv/bin/python -m pytest tests/unit
../.venv/bin/python scripts/check_asyncio_run.py
../.venv/bin/python scripts/check_http_500_leaks.py
../.venv/bin/python scripts/check_router_repositories.py
../.venv/bin/python scripts/check_text_sql.py
```

Grep must be clean:

```
rg 'StrictHostKeyChecking=no' backend --glob '*.py'
rg 'UserKnownHostsFile=/dev/null' backend --glob '*.py'
rg 'raise HTTPException' backend/services --glob '*.py'
rg 'relax_redirect=True' backend --glob '*.py'
```

`ENABLE_DEV_TOOLS=true ENV=production` process start must raise `RuntimeError` before serving.

---

## Explicit non-goals

- Splitting `step_runner.py` / `hatchet/workflows/workflow_run.py` / Nautobot `interface_workflow.py`.
- Deleting ISE sandbox scripts.
- Merging the two Nautobot metadata services.
- Changing Netmiko `ConnectHandler` host-key policy.
- Forcing `verify_ssl=True` for Nautobot/ISE.
- Adding `dashboard:*` permissions to the seed catalog (M3 reuses existing reads).
