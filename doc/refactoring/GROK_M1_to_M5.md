# Refactoring Plan — GROK M1 to M5

> Based on: `doc/GROK-ANALYSIS.md` §5.2  
> Date: 2026-07-25  
> Status: PLANNED  
> Issues: **M1** — Git `repo_path` allows `..` · **M2** — Filesystem sink `output_subdirectory` not fully sanitized · **M3** — SSRF via configurable source URLs · **M4** — Exception text in soft-error / non-standard 500 paths · **M5** — Full tracebacks stored on failed step results

---

## Implementation Order

Apply in this order so each step is independently reviewable and testable.

1. **M1** — Harden `repo_path()` (path escape under `data/git/`)
2. **M2** — Harden `FilesystemArtifactSink.output_subdirectory` (same `..` rule as file relative paths)
3. **M5** — Sanitize step-failure `error_message` persisted to DB (keep full traceback in worker logs only)
4. **M4** — Replace soft-error / bare 500 bodies that leak `str(e)` with `raise_internal_server_error` (or sanitized soft-error shape)
5. **M3** — Add outbound URL safety checks for ISE / Nautobot clients (scheme + host policy; DNS re-check at request time)
6. **Tests** — unit coverage for each helper + one regression per call site

> **Product constraint (M3):** Auxilium Manus targets on-prem NetDevOps. RFC1918 / corporate hostnames for ISE and Nautobot must remain allowed. Do **not** blanket-block private IPs. Block schemes other than `http`/`https`, URL userinfo, link-local / metadata addresses, and (by default) loopback — with an explicit env escape hatch for local lab.

---

## M1: Git `repo_path` allows `..` segments

**What:** `repo_path()` joins `PROJECT_ROOT / "data" / "git" / sub_path` where `sub_path` comes from repository `path` or `name` after only `lstrip("/")`. A value like `../../etc` escapes `data/git/`.

**Why:** A malicious (or mistaken) repository `path`/`name` can make clone/sync/file ops write or read outside the git data root.

**Files changed:**
- `backend/services/git/paths.py`
- `backend/tests/test_git_paths.py` (new)

**Call sites:** No signature change. All existing `repo_path(repository)` callers keep working; bad paths raise `ValueError` instead of returning an escaped `Path`.

### Code before

```python
# backend/services/git/paths.py

"""
Git Path Resolution Service.

This module handles path resolution for git repositories,
providing a single responsibility for determining where repositories
are stored on disk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from core.config import PROJECT_ROOT


def repo_path(repository: Dict) -> Path:
    """Compute the on-disk path for a repository.

    Args:
        repository: Repository metadata dict with keys like 'name' and optional 'path'.

    Returns:
        Absolute Path to the repository working directory under data/git/.

    Example:
        >>> repo = {"name": "my-configs", "path": "configs"}
        >>> repo_path(repo)
        Path('/data/git/configs')
    """
    sub_path = (repository.get("path") or repository["name"]).lstrip("/")
    return PROJECT_ROOT / "data" / "git" / sub_path
```

### Code after

```python
# backend/services/git/paths.py

"""
Git Path Resolution Service.

This module handles path resolution for git repositories,
providing a single responsibility for determining where repositories
are stored on disk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from core.config import PROJECT_ROOT

_GIT_DATA_ROOT = PROJECT_ROOT / "data" / "git"


def _sanitize_git_subpath(raw: str) -> str:
    """Normalize a repo subpath under data/git/; reject ``..`` and absolute paths."""
    normalized = raw.replace("\\", "/").strip()
    if normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.lstrip("/")

    parts = [part for part in normalized.split("/") if part and part != "."]
    if not parts:
        raise ValueError("repository path/name is empty after normalization")
    if ".." in parts:
        raise ValueError("repository path/name must not contain parent directory segments")
    # Reject Windows drive / UNC-style absolute leftovers after strip.
    if any(":" in part for part in parts):
        raise ValueError("repository path/name must be a relative path")

    return "/".join(parts)


def repo_path(repository: Dict) -> Path:
    """Compute the on-disk path for a repository under ``data/git/``.

    Rejects ``..`` segments and any resolved path that escapes the git data root.
    """
    raw = repository.get("path") or repository.get("name")
    if raw is None or not str(raw).strip():
        raise ValueError("repository path/name is required")

    sub_path = _sanitize_git_subpath(str(raw))
    root = _GIT_DATA_ROOT.resolve()
    candidate = (root / sub_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"repository path escapes data/git: {raw!r}") from exc
    return candidate
```

### Steps

1. Replace `backend/services/git/paths.py` with the after version (keep module docstring style).
2. Add `backend/tests/test_git_paths.py`:
   - Happy path: `{"name": "my-configs", "path": "configs"}` → path ends with `data/git/configs`.
   - Nested: `{"name": "x", "path": "team/a"}` → under `data/git/team/a`.
   - Reject: `path="../../etc"`, `path="../x"`, `path="/etc/passwd"`, `name=".."`.
   - Empty / whitespace-only `path` and missing `name` → `ValueError`.
3. Grep for callers that assume `repo_path` never raises; ensure create/update/sync surfaces `ValueError` as HTTP 400 (or existing validation path). If a caller swallows all `Exception` into 500, leave as-is for M1 — M4 covers safe 500s.
4. Run: `../.venv/bin/python -m pytest backend/tests/test_git_paths.py -q`

### Out of scope

- Moving `sanitize_relative_path` out of `workflow_steps.common` (architecture hygiene; separate from M1).
- Validating repository URL / credential fields.

---

## M2: Filesystem sink `output_subdirectory` not fully sanitized

**What:** `FilesystemArtifactSink` strips leading `/` `\` from `output_subdirectory` but does not reject `..`. Per-file `relative_path` already rejects `".." in normalized.parts`. A config like `output_subdirectory="../../outside"` escapes `settings.data_directory`.

**Why:** `store-artifact` with `destination=filesystem` builds the sink from step config (`workflow_steps/store_artifact/executor.py` → `_build_sink`). Escaping the data directory writes artifacts outside the intended export root.

**Files changed:**
- `backend/services/artifacts/sinks/filesystem_sink.py`
- `backend/workflow_steps/store_artifact/executor.py` (optional: sanitize before constructing sink so `ValueError` is raised as a step config error with a clear message)
- `backend/tests/test_filesystem_artifact_sink.py` (new) and/or extend `backend/tests/test_store_artifact_executor.py`

**Do not** import `workflow_steps.common.device_template.sanitize_relative_path` from the sink service — that would deepen the CLAUDE.md import-boundary violation already present in `git_sink.py`. Duplicate the small `..` / empty-parts check in the sink (same rules as the relative-path guard already in `_write_text_sync`).

### Code before

```python
# backend/services/artifacts/sinks/filesystem_sink.py

class FilesystemArtifactSink(ArtifactSink):
    """Write exports under ``{base_dir}/exports/{workflow_id}/{run_id}/``."""

    def __init__(self, base_dir: Path, *, output_subdirectory: str = "exports") -> None:
        self._base_dir = base_dir
        self._output_subdirectory = output_subdirectory.strip("/\\") or "exports"

    @property
    def destination(self) -> str:
        return "filesystem"

    def _run_root(self, *, workflow_id: str, run_id: str) -> Path:
        return self._base_dir / self._output_subdirectory / workflow_id / run_id

    # ... _write_text_sync already has:
    # normalized = Path(relative_path.lstrip("/\\"))
    # if normalized.is_absolute() or ".." in normalized.parts:
    #     raise ValueError(f"Unsafe export path: {relative_path!r}")
```

### Code after

```python
# backend/services/artifacts/sinks/filesystem_sink.py

class FilesystemArtifactSink(ArtifactSink):
    """Write exports under ``{base_dir}/{output_subdirectory}/{workflow_id}/{run_id}/``."""

    def __init__(self, base_dir: Path, *, output_subdirectory: str = "exports") -> None:
        self._base_dir = Path(base_dir)
        self._output_subdirectory = _sanitize_output_subdirectory(output_subdirectory)

    @property
    def destination(self) -> str:
        return "filesystem"

    def _run_root(self, *, workflow_id: str, run_id: str) -> Path:
        root = self._base_dir.resolve()
        candidate = (root / self._output_subdirectory / workflow_id / run_id).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                f"Unsafe export root escapes base_dir: {self._output_subdirectory!r}"
            ) from exc
        return candidate

    # _write_text_sync unchanged (keep the per-file ".." check)


def _sanitize_output_subdirectory(output_subdirectory: str) -> str:
    """Normalize subdirectory under the artifact base dir; reject ``..`` / absolute."""
    cleaned = (output_subdirectory or "").replace("\\", "/").strip().strip("/")
    if not cleaned:
        return "exports"
    parts = [part for part in cleaned.split("/") if part and part != "."]
    if not parts:
        return "exports"
    if ".." in parts:
        raise ValueError(
            f"output_subdirectory must not contain parent directory segments: "
            f"{output_subdirectory!r}"
        )
    if any(":" in part for part in parts):
        raise ValueError(
            f"output_subdirectory must be a relative path: {output_subdirectory!r}"
        )
    return "/".join(parts)
```

### Steps

1. Add `_sanitize_output_subdirectory` and use it in `__init__`; harden `_run_root` with `resolve()` + `relative_to(base)`.
2. Keep `_write_text_sync` relative-path check as defense-in-depth.
3. Tests (`test_filesystem_artifact_sink.py`):
   - Default / `"exports"` / `"team/exports"` accepted.
   - `"../outside"`, `"foo/../../etc"`, `"/abs"` rejected with `ValueError`.
   - After init with safe subdir, `write_text` with `relative_path="../x"` still fails (existing behavior).
4. Extend store-artifact executor test: config `output_subdirectory: "../escape"` → step raises `ValueError` (config error).
5. Run: `../.venv/bin/python -m pytest backend/tests/test_filesystem_artifact_sink.py backend/tests/test_store_artifact_executor.py -q`

### Optional follow-up (same PR or later)

Apply the same subdirectory sanitization to `GitArtifactSink.repository_subdirectory` if it only strips without rejecting `..` (see `services/artifacts/sinks/git_sink.py`). Not required to close M2 as written.

---

## M3: SSRF via configurable source URLs

**What:** ISE and Nautobot base URLs are admin-configured and passed straight into `httpx` with no scheme/host policy. ISE also allows `verify_ssl=False`. Mitigated today by source-admin permissions only.

**Why:** A compromised admin session (or overly broad permission grant) can point a source at link-local / cloud-metadata endpoints, or use non-HTTP schemes. DNS rebinding can change the resolved IP between configure-time and request-time if validation is only at create.

**Files changed:**
- `backend/core/safe_urls.py` (new)
- `backend/core/config.py` — optional flag `ALLOW_LOOPBACK_SOURCE_URLS` (default `False`)
- `backend/.env.example` — document the flag
- `backend/services/ise/client.py` — validate before `_do_request`
- `backend/services/nautobot/client.py` — validate before `_do_post` / `_do_request`
- `backend/services/ise/source_config_service.py` — validate on create/update (fail fast in UI)
- Nautobot source create/update path that persists `url` (same fail-fast; find the settings write site and call the same helper)
- `backend/tests/test_safe_urls.py` (new)

**Design rules (implement exactly):**

| Check | Action |
|-------|--------|
| Scheme | Allow only `http`, `https` |
| Userinfo (`user:pass@host`) | Reject |
| Hostname empty | Reject |
| Resolved IPs in `169.254.0.0/16`, `fe80::/10`, `::1`, `127.0.0.0/8` | Reject unless `settings.allow_loopback_source_urls` and address is loopback only |
| Cloud metadata hostnames | Reject literal `169.254.169.254` and hostname `metadata.google.internal` |
| RFC1918 (`10/8`, `172.16/12`, `192.168/16`), corporate DNS names | **Allow** (product requirement) |
| `verify_ssl=False` | Keep allowed; log a warning at request time when host is not clearly private — do not hard-fail |

Validate **at request time** (client) so DNS rebinding is caught. Also validate **at configure time** (source create/update) for fast UX errors.

### Code before

```python
# backend/services/ise/client.py  (ers_request — URL build, no safety check)

async def ers_request(
    self,
    endpoint: str,
    credentials: ISECredentials,
    method: str = "GET",
    data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not credentials.base_url or not credentials.username or not credentials.password:
        raise ISEValidationError("ISE base URL, username, and password are required")

    url = f"{credentials.base_url.rstrip('/')}/ers/config/{endpoint.lstrip('/')}"
    # ... proceeds to httpx with credentials.verify_ssl (may be False)
```

```python
# backend/services/nautobot/client.py  (graphql_query / rest_request)

graphql_url = f"{credentials.url.rstrip('/')}/api/graphql/"
# ... no host/scheme policy before httpx

api_url = f"{credentials.url.rstrip('/')}/api/{endpoint.lstrip('/')}"
# ... no host/scheme policy before httpx
```

```python
# backend/services/ise/source_config_service.py  (create_source)

value = ensure_value_source_id(
    {
        "url": url.rstrip("/"),
        "verify_ssl": verify_ssl,
        "timeout": timeout,
        "credential_id": credential["id"],
    },
    source_type="ise",
    source_id=source_id,
)
```

### Code after

```python
# backend/core/safe_urls.py  (new)

"""Outbound URL policy for admin-configured HTTP integrations (ISE, Nautobot)."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from core.config import settings

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_BLOCKED_HOSTNAMES = frozenset({"metadata.google.internal"})


class UnsafeURLError(ValueError):
    """Raised when a source URL violates the outbound HTTP policy."""


def validate_outbound_http_url(url: str, *, resolve_dns: bool = True) -> str:
    """Return a normalized URL or raise ``UnsafeURLError``.

    Allows RFC1918 / normal corporate hosts. Blocks non-http(s) schemes,
    URL userinfo, link-local / metadata targets, and (by default) loopback.
    When ``resolve_dns`` is True, every resolved A/AAAA address is checked
    (mitigates simple DNS rebinding between configure and request).
    """
    raw = (url or "").strip()
    if not raw:
        raise UnsafeURLError("URL is required")

    parsed = urlparse(raw)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise UnsafeURLError(f"URL scheme must be http or https, got {parsed.scheme!r}")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeURLError("URL must not contain embedded credentials")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise UnsafeURLError("URL host is required")
    if host in _BLOCKED_HOSTNAMES:
        raise UnsafeURLError(f"URL host is not allowed: {host}")

    # Literal IP in the URL
    try:
        _assert_ip_allowed(ipaddress.ip_address(host))
    except ValueError:
        pass  # hostname, not an IP literal

    if resolve_dns:
        _assert_resolved_hosts_allowed(host)

    return raw.rstrip("/")


def _assert_resolved_hosts_allowed(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"URL host could not be resolved: {host}") from exc
    if not infos:
        raise UnsafeURLError(f"URL host could not be resolved: {host}")
    for info in infos:
        sockaddr = info[4]
        _assert_ip_allowed(ipaddress.ip_address(sockaddr[0]))


def _assert_ip_allowed(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if ip.is_unspecified or ip.is_multicast:
        raise UnsafeURLError(f"URL resolves to a disallowed address: {ip}")
    if ip.is_loopback:
        if not getattr(settings, "allow_loopback_source_urls", False):
            raise UnsafeURLError(f"URL resolves to loopback address: {ip}")
        return
    if ip.is_link_local:
        raise UnsafeURLError(f"URL resolves to link-local address: {ip}")
    # Intentionally allow is_private (RFC1918) for on-prem ISE/Nautobot.
```

```python
# backend/services/ise/client.py  — at start of ers_request, after credential presence check

from core.safe_urls import UnsafeURLError, validate_outbound_http_url

# ...
try:
    base = validate_outbound_http_url(credentials.base_url, resolve_dns=True)
except UnsafeURLError as exc:
    raise ISEValidationError(str(exc)) from exc

url = f"{base}/ers/config/{endpoint.lstrip('/')}"
if not credentials.verify_ssl:
    logger.warning("ISE request with verify_ssl=False url_host=%s", urlparse(base).hostname)
```

```python
# backend/services/nautobot/client.py  — in graphql_query and rest_request

from core.safe_urls import UnsafeURLError, validate_outbound_http_url

# ...
try:
    base = validate_outbound_http_url(credentials.url, resolve_dns=True)
except UnsafeURLError as exc:
    raise NautobotValidationError(str(exc)) from exc

graphql_url = f"{base}/api/graphql/"
# ...
api_url = f"{base}/api/{endpoint.lstrip('/')}"
```

```python
# backend/services/ise/source_config_service.py  — create_source / update_source

from core.safe_urls import validate_outbound_http_url

# create_source:
safe_url = validate_outbound_http_url(url, resolve_dns=True)
value = ensure_value_source_id(
    {
        "url": safe_url,
        "verify_ssl": verify_ssl,
        "timeout": timeout,
        "credential_id": credential["id"],
    },
    ...
)

# update_source when url is not None:
updated_value["url"] = validate_outbound_http_url(url, resolve_dns=True)
```

```python
# backend/core/config.py  — add setting (namespaced like other flags)

allow_loopback_source_urls: bool = False  # env: ALLOW_LOOPBACK_SOURCE_URLS
```

```bash
# backend/.env.example
ALLOW_LOOPBACK_SOURCE_URLS=false
```

### Steps

1. Add `core/safe_urls.py` exactly as above (adjust import of `settings` if the project uses a Settings class attribute name differently — match existing env binding style in `core/config.py`).
2. Wire ISE + Nautobot clients and ISE source create/update.
3. Find Nautobot source URL persistence (settings key `sources.nautobot.*`) and call `validate_outbound_http_url` on create/update the same way.
4. Map `UnsafeURLError` / validation errors to HTTP 400 in source routers (existing `ValueError` → 400 paths should already cover this if the service raises `ValueError` subclasses).
5. Tests in `test_safe_urls.py` (mock `socket.getaddrinfo` where needed):
   - `https://nautobot.example.com` OK (mock resolve to public or RFC1918).
   - `https://10.0.0.5` OK (RFC1918 literal).
   - `http://169.254.169.254/` rejected.
   - `https://127.0.0.1` rejected unless flag True.
   - `ftp://x` / `https://user:pass@host/` rejected.
   - Client unit: `ers_request` / `graphql_query` call validate (mock) before httpx.
6. Run: `../.venv/bin/python -m pytest backend/tests/test_safe_urls.py -q`

### Out of scope

- Disabling `verify_ssl=False` entirely (labs need it).
- Blocking all private IPs (would break typical deployments).
- Browser/frontend URL checks (backend is the enforcement point).

---

## M4: Exception text in soft-error / non-standard 500 paths

**What:** Several git (and related) paths return or raise server failures with `str(e)` in the client-visible body, or raise bare `HTTPException(status_code=500, detail="...")` without `error_id` correlation via `raise_internal_server_error`.

**Why:** CLAUDE.md / `core.safe_http_errors`: 5xx responses must not expose raw exception text; clients should see `{message, error_id}` only. Soft-error JSON bodies that embed `str(e)` are the same leak class even when status is 200.

**Files changed (minimum set from GROK-ANALYSIS + current leaks):**
- `backend/routers/git/operations.py` — `/status` soft-error; `/debug` soft-error
- `backend/routers/git/repositories.py` — bare `HTTPException(status_code=500, ...)` without `error_id`
- `backend/services/git/csv_service.py` — `detail=f"...{str(e)}"` on 500 (service raises HTTPException — still client-visible)
- `backend/services/git/file_service.py` — same pattern (`detail="Failed to get files: %s" % str(e)` and siblings)
- Optionally: `backend/routers/sources/nautobot/crud.py` bare 500s without `error_id` (hard-coded strings are OK for secrecy but should still use `raise_internal_server_error` for correlation)

**Keep as-is:** Client-facing **400/404** with `detail=str(exc)` for validation / not-found (explicitly called out as acceptable in GROK-ANALYSIS).

**Do not** put `str(e)` into DB fields like `sync_status` if those are later returned to clients via status APIs — prefer a short stable token (`"error"`) plus server-side logs with `error_id`. Truncate: for sync_status historically storing `error: {str(e)}`, change to `error` or `error:{error_id}` only.

### Code before

```python
# backend/routers/git/operations.py — get_repository_status

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error getting repository status: %s", e)
        return {
            "success": False,
            "message": f"Failed to get repository status: {str(e)}",
        }


# backend/routers/git/operations.py — debug_git

    except Exception as e:
        return {"status": "error", "error": str(e), "error_type": type(e).__name__}


# backend/routers/git/operations.py — sync_repository / remove_and_sync_repository
# (partial: sync_status still embeds str(e))

    except Exception as e:
        logger.error("Error syncing repository %s: %s", repo_id, e)
        git_repo_manager.update_sync_status(repo_id, f"error: {str(e)}")
        raise_internal_server_error(logger, "Internal error syncing repository", e)


# backend/routers/git/repositories.py

        if not success:
            raise HTTPException(status_code=500, detail="Failed to update repository")
# ...
            raise HTTPException(
                status_code=500, detail="Failed to retrieve updated repository"
            )
# ...
            raise HTTPException(status_code=500, detail="Failed to delete repository")


# backend/services/git/csv_service.py

        except Exception as e:
            logger.error("Error listing CSV files: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error listing CSV files: {str(e)}",
            ) from e
```

### Code after

```python
# backend/routers/git/operations.py — get_repository_status

from core.safe_http_errors import internal_error_detail, raise_internal_server_error
import uuid

    except HTTPException:
        raise
    except Exception as e:
        error_id = str(uuid.uuid4())
        logger.error(
            "Error getting repository status (error_id=%s)",
            error_id,
            exc_info=True,
            extra={"error_id": error_id},
        )
        return {
            "success": False,
            "message": "Failed to get repository status",
            "error_id": error_id,
        }


# backend/routers/git/operations.py — debug_git
# Prefer hard 500 with correlation over soft body leaking exception text.

    except HTTPException:
        raise
    except Exception as e:
        raise_internal_server_error(logger, f"Git debug failed for repo {repo_id}", e)


# backend/routers/git/operations.py — sync failure path

    except Exception as e:
        # raise_internal_server_error logs with error_id; reuse a local id for DB status
        error_id = str(uuid.uuid4())
        logger.error(
            "Error syncing repository %s (error_id=%s)",
            repo_id,
            error_id,
            exc_info=True,
            extra={"error_id": error_id},
        )
        git_repo_manager.update_sync_status(repo_id, f"error:{error_id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=internal_error_detail(error_id=error_id),
        ) from e


# backend/routers/git/repositories.py

        if not success:
            raise_internal_server_error(
                logger, f"Failed to update repository {repo_id}"
            )
# same for retrieve-updated and delete failures


# backend/services/git/csv_service.py  (and file_service.py equivalents)

from core.safe_http_errors import raise_internal_server_error

        except HTTPException:
            raise
        except Exception as e:
            raise_internal_server_error(logger, "Error listing CSV files", e)
```

> **Note on `raise_internal_server_error` signature:** Existing helper already accepts `(logger, log_message, exc=None)` and returns `detail={"message": INTERNAL_ERROR_MESSAGE, "error_id": ...}`. Prefer calling it directly whenever the endpoint can raise instead of returning a soft-error body. Soft-error bodies (status 200 + `success: false`) must still omit `str(e)` and include `error_id`.

### Steps

1. Fix `operations.py` soft-error bodies (`/status`, `/debug`) and sync_status `str(e)` persistence.
2. Replace bare `HTTPException(500, ...)` in `repositories.py` with `raise_internal_server_error`.
3. Sweep `csv_service.py` and `file_service.py` 500s that interpolate `str(e)` → `raise_internal_server_error`.
4. For `routers/sources/nautobot/crud.py` bare 500s with static detail strings: switch to `raise_internal_server_error` so clients get `error_id` (static message alone is not a leak, but lacks correlation).
5. Run regression guard: `../.venv/bin/python backend/scripts/check_http_500_leaks.py`
6. Manually confirm `/api/proxy/git/{id}/status` on a broken repo returns `success: false` **without** a Python traceback/exception string, and includes `error_id`.

### Out of scope

- Refactoring fat git routers into thinner services (architecture; not M4).
- Changing 400/404 `detail=str(e)` validation responses.

---

## M5: Full tracebacks stored on failed step results

**What:** On executor failure, `StepRunner` persists `traceback.format_exc()[:4000]` into `WorkflowStepResult.error_message`. Operators with run-read permission see filesystem paths and internal frames in the API/UI.

**Why:** Full tracebacks belong in worker logs (`exc_info=True` already). DB/API should store a short sanitized message plus a correlation id that matches the log line.

**Files changed:**
- `backend/services/execution/step_runner.py`
- `backend/tests/test_step_runner_errors.py` (new) — or extend the nearest existing step_runner test module if one exists

**Preserve:** `logger.error(..., exc_info=True)` so ops still have the full stack in logs.

### Code before

```python
# backend/services/execution/step_runner.py  (inside execute_one / per-step try)

        except Exception:
            logger.error(
                "Step failed node_id=%s type=%s run_id=%s",
                node_id,
                step_type,
                run.id,
                exc_info=True,
            )
            import traceback

            self.repo.update_step_result(
                step_result,
                status="failed",
                error_message=traceback.format_exc()[:4000],
                finished_at=datetime.now(timezone.utc),
            )
            return False
```

### Code after

```python
# backend/services/execution/step_runner.py

import uuid
# (add at module top with other imports; remove inline `import traceback`)

        except Exception as exc:
            error_id = str(uuid.uuid4())
            logger.error(
                "Step failed node_id=%s type=%s run_id=%s error_id=%s",
                node_id,
                step_type,
                run.id,
                error_id,
                exc_info=True,
                extra={"error_id": error_id},
            )
            # Persist a safe, short message only — full traceback stays in worker logs.
            safe_message = (
                f"Step failed ({type(exc).__name__}). "
                f"See worker logs for error_id={error_id}."
            )
            self.repo.update_step_result(
                step_result,
                status="failed",
                error_message=safe_message[:4000],
                finished_at=datetime.now(timezone.utc),
            )
            return False
```

> **Exception type name is OK** to persist (`ValueError`, `RuntimeError`, `ISEAPIError`) — it aids operators without dumping frames/paths. Do **not** persist `str(exc)` if it may contain secrets, host paths, or response bodies; type name + `error_id` is enough.

If there are **other** `traceback.format_exc()` writes into step results / run error fields in the same module (or Hatchet workflow wrapper), apply the same pattern. Grep before finishing:

```bash
rg -n "format_exc|error_message=" backend/services/execution backend/hatchet
```

### Steps

1. Patch the `except Exception` block in `step_runner.py` as above (module-level `import uuid`; delete inline `import traceback` if unused elsewhere in the file).
2. Grep for other persisted tracebacks; fix any siblings the same way.
3. Test: mock an executor that raises `RuntimeError("secret path /var/app")`; assert persisted `error_message`:
   - contains `error_id=`
   - contains `RuntimeError`
   - does **not** contain `/var/app` or `Traceback`
4. Run a failing workflow locally once; confirm UI shows the sanitized message and logs show the full stack with the same `error_id`.
5. Run: `../.venv/bin/python -m pytest backend/tests/test_step_runner_errors.py -q` (or the chosen test path)

### Out of scope

- Frontend copy changes for the new message shape (UI already renders `error_message` as text).
- Redacting secrets inside successful step outputs (that is H1, see `doc/refactoring/GROK_H1_H2.md`).

---

## Verification checklist (all of M1–M5)

| # | Check | Command / action |
|---|-------|------------------|
| 1 | M1 unit tests | `../.venv/bin/python -m pytest backend/tests/test_git_paths.py -q` |
| 2 | M2 unit tests | `../.venv/bin/python -m pytest backend/tests/test_filesystem_artifact_sink.py backend/tests/test_store_artifact_executor.py -q` |
| 3 | M3 unit tests | `../.venv/bin/python -m pytest backend/tests/test_safe_urls.py -q` |
| 4 | M5 unit tests | `../.venv/bin/python -m pytest backend/tests/test_step_runner_errors.py -q` |
| 5 | M4 leak guard | `../.venv/bin/python backend/scripts/check_http_500_leaks.py` |
| 6 | No new router→repo imports | `../.venv/bin/python backend/scripts/check_router_repositories.py` |
| 7 | Manual: git status soft-error | Break a repo path; `GET /api/proxy/git/{id}/status` → no `str(e)` in body |
| 8 | Manual: store-artifact escape | Workflow with `output_subdirectory: "../x"` → step config error |
| 9 | Manual: step failure UI | Force executor exception → run detail shows type + `error_id`, not traceback |

---

## Done when

- [ ] `repo_path()` rejects `..` and resolved escapes from `data/git/`
- [ ] `FilesystemArtifactSink` rejects `..` in `output_subdirectory` (and resolved escape from `base_dir`)
- [ ] ISE/Nautobot requests validate outbound URLs (scheme/userinfo/link-local/metadata/loopback policy); RFC1918 still works
- [ ] Git soft-error / 500 paths no longer embed `str(e)`; 5xx use `error_id`
- [ ] Failed step results store sanitized message + `error_id`; full traceback only in logs
- [ ] New unit tests green; `check_http_500_leaks.py` green
