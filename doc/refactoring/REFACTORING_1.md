# Refactoring Plan 1 — Git Router & Repository Layer

> Based on: `doc/refactoring/ANALYSIS_1.md`
> Date: 2026-06-25
> Status: PLAN (not yet implemented)

---

## Implementation Order

Apply in this order to minimise risk. Each step is independently deployable.

1. **HIGH-1** — Remove dead import in `git/files.py` (safe, isolated, zero-risk)
2. **HIGH-3** — Fix 5xx exception leaks in `git/operations.py` (safe, isolated; skip if doing HIGH-2 next, as HIGH-2 removes those lines)
3. **HIGH-2** — Replace router sync logic with service delegation in `git/operations.py` (removes the code addressed by HIGH-3 as a side effect)
4. **MEDIUM-6** — Fix `GitRepositoryRepository` DI bypass (refactor, no behavioural change)
5. **MEDIUM-4** — Extract `GitDebugService` from `git/debug.py` (new file + thin router)
6. **MEDIUM-5** — Extract `GitVersionControlService` from `git/version_control.py` (new file + thin router)
7. **MEDIUM-7** — Rename `InventoryPersistenceService` → `InventoryService` (broad rename, do last)

> **Note:** HIGH-2 and HIGH-3 touch the same two lines in `operations.py`. If you apply HIGH-2 first, HIGH-3 is already resolved. If you apply HIGH-3 first, simply replace the two `HTTPException(status_code=500, …)` lines and then do HIGH-2 on top.

---

## HIGH-1: Remove Dead Import in `routers/git/files.py`

**What:** Line 59 contains a lazy import `from services.settings.manager import SettingsManager` that references a module that does not exist — the endpoint crashes at runtime.

**Why:** Violates CLAUDE.md "Task Completion" rule (all related code must be complete); also `services.settings.manager` never existed in this codebase.

**Files changed:**
- `backend/routers/git/files.py`

### Code before

```python
# backend/routers/git/files.py  lines 51-71

@router.get("/files/{file_path:path}/complete-history")
async def get_file_complete_history(
    repo_id: int,
    file_path: str,
    from_commit: str = None,
    current_user: dict = Depends(get_current_user),
    cache_service=Depends(get_cache_service),
):
    from services.settings.manager import SettingsManager

    settings_manager = SettingsManager()

    cache_cfg = settings_manager.get_cache_settings()
    return _git_file_service.get_file_history(
        repo_id,
        file_path,
        from_commit,
        cache_service,
        cache_enabled=cache_cfg.get("enabled", True),
        cache_ttl=int(cache_cfg.get("ttl_seconds", 600)),
    )
```

### Code after

```python
# backend/routers/git/files.py  lines 51-62

@router.get("/files/{file_path:path}/complete-history")
async def get_file_complete_history(
    repo_id: int,
    file_path: str,
    from_commit: str = None,
    current_user: dict = Depends(get_current_user),
    cache_service=Depends(get_cache_service),
):
    return _git_file_service.get_file_history(
        repo_id,
        file_path,
        from_commit,
        cache_service,
    )
```

**Rationale for defaults:** `GitFileService.get_file_history` already declares `cache_enabled: bool = True` and `cache_ttl: int = 600` as its defaults. These match the values the dead `SettingsManager` call was trying to read. The `cache_service` is still passed so caching works when Redis is available.

### Steps

1. Open `backend/routers/git/files.py`.
2. Replace the entire `get_file_complete_history` function body with the "after" version above.
3. Verify: `grep -n "SettingsManager" backend/routers/git/files.py` → should return nothing.
4. Run `ruff check backend/routers/git/files.py` — should pass.

---

## HIGH-2: Replace Router Sync Logic with Service Delegation in `routers/git/operations.py`

**What:** `sync_repository` (lines 81–225) and `remove_and_sync_repository` (lines 228–351) duplicate ~270 lines of git clone/pull logic that already exists in `services/git/operations.py` (`GitOperationsService.sync_repository` and `GitOperationsService.remove_and_sync`). The router must be a thin wrapper only.

**Why:** CLAUDE.md: "Thin routers that delegate to services"; "Business logic in routers" is explicitly listed as an INCORRECT practice.

**Files changed:**
- `backend/routers/git/operations.py` (replace two large handlers)

**No new files needed** — `GitOperationsService` already exists with the correct methods. `get_git_operations_service` is already imported in the router.

### Code before — `sync_repository` handler (lines 80–225)

```python
@router.post("/sync")
async def sync_repository(
    repo_id: int,
    current_user: dict = Depends(get_current_user),
    git_auth_service=Depends(get_git_auth_service),
    git_cache_service=Depends(get_git_cache_service),
):
    """Sync a git repository (clone if not exists, pull if exists)."""
    try:
        # Load repository
        repository = git_repo_manager.get_repository(repo_id)
        if not repository:
            raise HTTPException(status_code=404, detail="Repository not found")

        git_repo_manager.update_sync_status(repo_id, "syncing")

        # Compute repo path (uses configured 'path' or fallback to 'name')
        repo_path = str(git_repo_path(repository))

        logger.info(
            "Syncing repository '%s' to path: %s", repository["name"], repo_path
        )
        logger.info("Repository URL: %s", repository["url"])
        logger.info("Repository branch: %s", repository["branch"])

        os.makedirs(os.path.dirname(repo_path), exist_ok=True)

        # Determine action: clone or pull
        repo_dir_exists = os.path.exists(repo_path)
        is_git_repo = os.path.isdir(os.path.join(repo_path, ".git"))
        needs_clone = not is_git_repo

        success = False
        message = ""

        # Use authentication service for all auth operations
        with git_auth_service.setup_auth_environment(repository) as (
            clone_url,
            resolved_username,
            resolved_token,
            ssh_key_path,
        ):
            if needs_clone:
                # Backup non-repo directory if present
                if repo_dir_exists and not is_git_repo:
                    parent_dir = os.path.dirname(
                        repo_path.rstrip(os.sep)
                    ) or os.path.dirname(repo_path)
                    base_name = os.path.basename(os.path.normpath(repo_path))
                    backup_path = os.path.join(
                        parent_dir, f"{base_name}_backup_{int(time.time())}"
                    )
                    shutil.move(repo_path, backup_path)
                    logger.info("Backed up existing directory to %s", backup_path)

                # SSL env toggle
                try:
                    if not repository.get("verify_ssl", True):
                        logger.warning(
                            "Git SSL verification disabled - not recommended for production"
                        )
                    with set_ssl_env(repository):
                        logger.info(
                            "Cloning branch %s into %s", repository["branch"], repo_path
                        )
                        Repo.clone_from(
                            clone_url, repo_path, branch=repository["branch"]
                        )

                    if not os.path.isdir(os.path.join(repo_path, ".git")):
                        raise GitCommandError(
                            "clone", 1, b"", b".git not found after clone"
                        )

                    success = True
                    message = f"Repository '{repository['name']}' cloned successfully to {repo_path}"
                    logger.info(message)
                except GitCommandError as gce:
                    err = str(gce)
                    logger.error("Git clone failed: %s", err)
                    if "authentication" in err.lower():
                        message = (
                            "Authentication failed. Please check your Git credentials."
                        )
                    elif "not found" in err.lower():
                        message = f"Repository or branch not found. URL: {repository['url']} Branch: {repository['branch']}"
                    else:
                        message = f"Git clone failed: {err}"
                except Exception as e:
                    logger.error("Unexpected error during Git clone: %s", e)
                    message = f"Unexpected error: {str(e)}"
                finally:
                    # Cleanup empty directory after failed clone
                    try:
                        if (
                            not success
                            and os.path.isdir(repo_path)
                            and not os.listdir(repo_path)
                        ):
                            shutil.rmtree(repo_path)
                            logger.info(
                                "Removed empty directory after failed clone: %s",
                                repo_path,
                            )
                    except Exception as ce:
                        logger.warning("Cleanup after failed clone skipped: %s", ce)
            else:
                # Pull latest
                try:
                    repo = Repo(repo_path)
                    origin = repo.remotes.origin

                    # Update remote URL with authenticated URL if using token auth
                    if resolved_token and "http" in repository["url"]:
                        try:
                            origin.set_url(clone_url)
                        except Exception as e:
                            logger.debug("Skipping remote URL update: %s", e)

                    with set_ssl_env(repository):
                        origin.pull(repository["branch"])
                        success = True
                        message = (
                            f"Repository '{repository['name']}' updated successfully"
                        )
                        logger.info(message)
                except Exception as e:
                    logger.error("Error during Git pull: %s", e)
                    message = f"Pull failed: {str(e)}"

        # Final status
        if success:
            git_repo_manager.update_sync_status(repo_id, "synced")
            # Invalidate cache after successful sync
            git_cache_service.invalidate_repo(repo_id)
            return {"success": True, "message": message, "repository_path": repo_path}
        else:
            git_repo_manager.update_sync_status(repo_id, f"error: {message}")
            raise HTTPException(status_code=500, detail=message)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error syncing repository %s: %s", repo_id, e)
        git_repo_manager.update_sync_status(repo_id, f"error: {str(e)}")
        raise_internal_server_error(logger, "Internal error", e)
```

### Code before — `remove_and_sync_repository` handler (lines 228–351)

```python
@router.post("/remove-and-sync")
async def remove_and_sync_repository(
    repo_id: int,
    current_user: dict = Depends(get_current_user),
    git_auth_service=Depends(get_git_auth_service),
    git_cache_service=Depends(get_git_cache_service),
):
    """Remove existing repository and clone fresh copy."""
    try:
        # Get repository details
        repository = git_repo_manager.get_repository(repo_id)
        if not repository:
            raise HTTPException(status_code=404, detail="Repository not found")

        git_repo_manager.update_sync_status(repo_id, "removing-and-syncing")

        # Resolve repository working directory
        repo_path = str(git_repo_path(repository))

        logger.info(
            "Remove and sync repository '%s' at path: %s", repository["name"], repo_path
        )

        # Remove existing directory if it exists
        if os.path.exists(repo_path):
            # Create backup with timestamp
            parent_dir = os.path.dirname(repo_path.rstrip(os.sep)) or os.path.dirname(
                repo_path
            )
            base_name = os.path.basename(os.path.normpath(repo_path))
            backup_path = os.path.join(
                parent_dir, f"{base_name}_removed_{int(time.time())}"
            )

            try:
                shutil.move(repo_path, backup_path)
                logger.info("Existing repository backed up to %s", backup_path)
            except Exception as e:
                logger.warning("Could not backup existing repository: %s", e)
                # Try to remove directly
                shutil.rmtree(repo_path, ignore_errors=True)
                logger.info("Removed existing repository at %s", repo_path)

        # Ensure parent directory exists
        os.makedirs(os.path.dirname(repo_path), exist_ok=True)

        # Clone fresh copy using authentication service
        success = False
        message = ""

        with git_auth_service.setup_auth_environment(repository) as (
            clone_url,
            resolved_username,
            resolved_token,
            ssh_key_path,
        ):
            try:
                if not repository.get("verify_ssl", True):
                    logger.warning(
                        "Git SSL verification disabled - not recommended for production"
                    )

                with set_ssl_env(repository):
                    logger.info(
                        "Cloning fresh copy of branch %s into %s",
                        repository["branch"],
                        repo_path,
                    )
                    Repo.clone_from(clone_url, repo_path, branch=repository["branch"])

                if not os.path.isdir(os.path.join(repo_path, ".git")):
                    raise GitCommandError(
                        "clone", 1, b"", b".git not found after clone"
                    )

                success = True
                message = f"Repository '{repository['name']}' removed and re-cloned successfully"
                logger.info(message)

            except GitCommandError as gce:
                err = str(gce)
                logger.error("Git clone failed: %s", err)
                if "authentication" in err.lower():
                    message = (
                        "Authentication failed. Please check your Git credentials."
                    )
                elif "not found" in err.lower():
                    message = f"Repository or branch not found. URL: {repository['url']} Branch: {repository['branch']}"
                else:
                    message = f"Git clone failed: {err}"
            except Exception as e:
                logger.error("Unexpected error during Git clone: %s", e)
                message = f"Unexpected error: {str(e)}"
            finally:
                # Cleanup empty directory after failed clone
                try:
                    if (
                        not success
                        and os.path.isdir(repo_path)
                        and not os.listdir(repo_path)
                    ):
                        shutil.rmtree(repo_path)
                        logger.info(
                            "Removed empty directory after failed clone: %s", repo_path
                        )
                except Exception as ce:
                    logger.warning("Cleanup after failed clone skipped: %s", ce)

        # Final status update
        if success:
            git_repo_manager.update_sync_status(repo_id, "synced")
            # Invalidate cache after successful sync
            git_cache_service.invalidate_repo(repo_id)
            return {"success": True, "message": message, "repository_path": repo_path}
        else:
            git_repo_manager.update_sync_status(repo_id, f"error: {message}")
            raise HTTPException(status_code=500, detail=message)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error removing and syncing repository %s: %s", repo_id, e)
        git_repo_manager.update_sync_status(repo_id, f"error: {str(e)}")
        raise_internal_server_error(logger, "Internal error", e)
```

### Code after — both handlers replaced

Replace both handlers with the following thin wrappers. **Also update the import block** at the top of the file.

**Updated imports** (replace the existing import block):

```python
# backend/routers/git/operations.py — top of file (replace entire import section)

"""
Git repository operations router - Repository sync, status, and management operations.
Handles syncing, status checking, and operational tasks for Git repositories.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from core.auth import get_current_user
from core.safe_http_errors import raise_internal_server_error
from dependencies import (
    get_git_cache_service,
    get_git_operations_service,
)
from services.git.shared_utils import get_git_repo_by_id, git_repo_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/git/{repo_id}", tags=["git-operations"])
```

**Removed imports** (no longer needed after HIGH-2):
- `import os`
- `import shutil`
- `import time`
- `from git import GitCommandError, Repo`
- `get_git_auth_service` from `dependencies`
- `from services.git.env import set_ssl_env`
- `from services.git.paths import repo_path as git_repo_path`

**New `sync_repository` handler:**

```python
@router.post("/sync")
async def sync_repository(
    repo_id: int,
    current_user: dict = Depends(get_current_user),
    git_operations_service=Depends(get_git_operations_service),
    git_cache_service=Depends(get_git_cache_service),
):
    """Sync a git repository (clone if not exists, pull if exists)."""
    try:
        repository = git_repo_manager.get_repository(repo_id)
        if not repository:
            raise HTTPException(status_code=404, detail="Repository not found")

        git_repo_manager.update_sync_status(repo_id, "syncing")
        result = git_operations_service.sync_repository(repository)

        if result.success:
            git_repo_manager.update_sync_status(repo_id, "synced")
            git_cache_service.invalidate_repo(repo_id)
            return {
                "success": True,
                "message": result.message,
                "repository_path": result.repository_path,
            }

        git_repo_manager.update_sync_status(repo_id, f"error: {result.message}")
        raise_internal_server_error(logger, result.message)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error syncing repository %s: %s", repo_id, e)
        git_repo_manager.update_sync_status(repo_id, f"error: {str(e)}")
        raise_internal_server_error(logger, "Internal error syncing repository", e)
```

**New `remove_and_sync_repository` handler:**

```python
@router.post("/remove-and-sync")
async def remove_and_sync_repository(
    repo_id: int,
    current_user: dict = Depends(get_current_user),
    git_operations_service=Depends(get_git_operations_service),
    git_cache_service=Depends(get_git_cache_service),
):
    """Remove existing repository and clone fresh copy."""
    try:
        repository = git_repo_manager.get_repository(repo_id)
        if not repository:
            raise HTTPException(status_code=404, detail="Repository not found")

        git_repo_manager.update_sync_status(repo_id, "removing-and-syncing")
        result = git_operations_service.remove_and_sync(repository)

        if result.success:
            git_repo_manager.update_sync_status(repo_id, "synced")
            git_cache_service.invalidate_repo(repo_id)
            return {
                "success": True,
                "message": result.message,
                "repository_path": result.repository_path,
            }

        git_repo_manager.update_sync_status(repo_id, f"error: {result.message}")
        raise_internal_server_error(logger, result.message)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error removing and syncing repository %s: %s", repo_id, e)
        git_repo_manager.update_sync_status(repo_id, f"error: {str(e)}")
        raise_internal_server_error(logger, "Internal error removing and syncing repository", e)
```

**Also keep** the unchanged helper function and the three other handlers (`get_cached_commits`, `get_repository_status`, `get_repository_info`, `debug_git`) exactly as they are. Only the two `POST` handlers above change.

### Steps

1. Open `backend/routers/git/operations.py`.
2. Replace the entire import block (lines 1–27) with the "Updated imports" block above.
3. Delete the entire body of `sync_repository` (lines 80–225) and replace with the new thin handler.
4. Delete the entire body of `remove_and_sync_repository` (lines 228–351) and replace with the new thin handler.
5. Verify: `grep -n "git_auth_service\|import shutil\|import time\|from git import\|set_ssl_env\|git_repo_path" backend/routers/git/operations.py` → should return nothing.
6. Run `ruff check backend/routers/git/operations.py` — should pass.
7. Manually test both endpoints end-to-end (sync a repo and remove-and-sync a repo).

> **Behavioural note:** The router previously created timestamp-named backup directories before removing (`_removed_<ts>`). `GitOperationsService.remove_and_sync` uses `shutil.rmtree(ignore_errors=True)` directly — no backup. This is intentional: the service owns this behaviour. If the backup must be preserved, add it to the service instead, not the router.

---

## HIGH-3: Fix 5xx Exception Leaks in `routers/git/operations.py`

**What:** `HTTPException(status_code=500, detail=message)` on lines 218 and 344 passes potentially exception-derived strings directly in the HTTP response body.

**Why:** CLAUDE.md security checklist: "Never put raw exception text in `HTTPException(detail=…)` for server errors. Use `core.safe_http_errors.raise_internal_server_error`."

> **If you apply HIGH-2 first, HIGH-3 is automatically resolved** — the two offending lines are deleted. Apply this section only if doing HIGH-3 in isolation before HIGH-2.

**Files changed:**
- `backend/routers/git/operations.py`

### Code before (line 217–218, inside `sync_repository`)

```python
        else:
            git_repo_manager.update_sync_status(repo_id, f"error: {message}")
            raise HTTPException(status_code=500, detail=message)
```

### Code after

```python
        else:
            git_repo_manager.update_sync_status(repo_id, f"error: {message}")
            raise_internal_server_error(logger, message)
```

### Code before (line 343–344, inside `remove_and_sync_repository`)

```python
        else:
            git_repo_manager.update_sync_status(repo_id, f"error: {message}")
            raise HTTPException(status_code=500, detail=message)
```

### Code after

```python
        else:
            git_repo_manager.update_sync_status(repo_id, f"error: {message}")
            raise_internal_server_error(logger, message)
```

`raise_internal_server_error` is already imported at the top of the file — no import changes needed.

### Steps

1. Open `backend/routers/git/operations.py`.
2. Replace line 218 as shown above.
3. Replace line 344 as shown above.
4. Verify: `grep -n "HTTPException(status_code=500" backend/routers/git/operations.py` → should return nothing.

---

## MEDIUM-4: Extract `GitDebugService` from `routers/git/debug.py`

**What:** 746-line router has all debug logic (read/write/delete/push tests and full diagnostics) embedded directly in route handlers. Extract into a dedicated service.

**Why:** CLAUDE.md: "Business logic in routers" is an INCORRECT practice. Routers must be thin wrappers.

**Files changed / created:**
- `backend/services/git/debug_service.py` — **new file**
- `backend/routers/git/debug.py` — replace with thin wrappers
- `backend/service_factory.py` — add `build_git_debug_service`
- `backend/dependencies.py` — add `get_git_debug_service`

---

### New file: `backend/services/git/debug_service.py`

```python
"""Debug and diagnostic operations for git repositories."""

from __future__ import annotations

import logging
import os
import ssl
from datetime import datetime
from pathlib import Path
from typing import Any

from services.git.config import set_git_author
from services.git.env import set_ssl_env
from services.git.shared_utils import get_git_repo_by_id, git_repo_manager

logger = logging.getLogger(__name__)


class GitDebugService:
    """Encapsulates all debug/diagnostic operations for a git repository."""

    def test_read(self, repo_id: int) -> dict[str, Any]:
        """Test reading the debug sentinel file from the repository."""
        repository = git_repo_manager.get_repository(repo_id)
        if not repository:
            raise ValueError(f"Repository {repo_id} not found")

        repo = get_git_repo_by_id(repo_id)
        repo_path = Path(repo.working_dir)
        test_file_path = repo_path / ".cockpit_debug_test.txt"

        if not test_file_path.exists():
            return {
                "success": False,
                "message": "Test file does not exist",
                "details": {
                    "file_path": str(test_file_path),
                    "repository_path": str(repo_path),
                    "exists": False,
                    "suggestion": "Use the 'Write' operation to create the test file first",
                },
            }

        try:
            content = test_file_path.read_text()
            return {
                "success": True,
                "message": "File read successfully",
                "details": {
                    "file_path": str(test_file_path),
                    "content": content,
                    "size_bytes": len(content),
                    "readable": True,
                },
            }
        except PermissionError as e:
            return {
                "success": False,
                "message": "Permission denied reading file",
                "details": {
                    "error": str(e),
                    "file_path": str(test_file_path),
                    "error_type": "PermissionError",
                    "suggestion": "Check file system permissions for the repository directory",
                },
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Error reading file: {str(e)}",
                "details": {
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "file_path": str(test_file_path),
                },
            }

    def test_write(self, repo_id: int) -> dict[str, Any]:
        """Test writing the debug sentinel file to the repository."""
        repository = git_repo_manager.get_repository(repo_id)
        if not repository:
            raise ValueError(f"Repository {repo_id} not found")

        repo = get_git_repo_by_id(repo_id)
        repo_path = Path(repo.working_dir)
        test_file_path = repo_path / ".cockpit_debug_test.txt"

        test_content = (
            f"Cockpit Debug Test\n"
            f"Timestamp: {datetime.now().isoformat()}\n"
            f"Repository: {repository['name']}\n"
        )

        try:
            test_file_path.write_text(test_content)

            if not test_file_path.exists():
                return {
                    "success": False,
                    "message": "File write appeared to succeed but file does not exist",
                    "details": {
                        "file_path": str(test_file_path),
                        "error_type": "VerificationError",
                    },
                }

            written_content = test_file_path.read_text()
            success = written_content == test_content

            repo_status = "unknown"
            try:
                repo_status = (
                    "modified (file created but not committed)"
                    if repo.is_dirty(untracked_files=True)
                    else "clean"
                )
            except Exception:
                repo_status = "status check failed"

            return {
                "success": success,
                "message": "File written successfully" if success else "File written but verification failed",
                "details": {
                    "file_path": str(test_file_path),
                    "content_length": len(test_content),
                    "verified": success,
                    "git_status": repo_status,
                    "writable": True,
                },
            }

        except PermissionError as e:
            return {
                "success": False,
                "message": "Permission denied writing file",
                "details": {
                    "error": str(e),
                    "file_path": str(test_file_path),
                    "error_type": "PermissionError",
                    "suggestion": "Check file system permissions for the repository directory",
                    "directory_writable": os.access(str(repo_path), os.W_OK),
                },
            }
        except OSError as e:
            return {
                "success": False,
                "message": f"OS error writing file: {str(e)}",
                "details": {
                    "error": str(e),
                    "error_type": "OSError",
                    "file_path": str(test_file_path),
                    "suggestion": "Check disk space and file system health",
                },
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Error writing file: {str(e)}",
                "details": {
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "file_path": str(test_file_path),
                },
            }

    def test_delete(self, repo_id: int) -> dict[str, Any]:
        """Test deleting the debug sentinel file from the repository."""
        repository = git_repo_manager.get_repository(repo_id)
        if not repository:
            raise ValueError(f"Repository {repo_id} not found")

        repo = get_git_repo_by_id(repo_id)
        repo_path = Path(repo.working_dir)
        test_file_path = repo_path / ".cockpit_debug_test.txt"

        if not test_file_path.exists():
            return {
                "success": False,
                "message": "Test file does not exist, nothing to delete",
                "details": {"file_path": str(test_file_path), "exists": False},
            }

        try:
            test_file_path.unlink()

            if test_file_path.exists():
                return {
                    "success": False,
                    "message": "File deletion appeared to succeed but file still exists",
                    "details": {
                        "file_path": str(test_file_path),
                        "error_type": "VerificationError",
                    },
                }

            repo_status = "unknown"
            try:
                repo_status = (
                    "modified (file deleted but not committed)"
                    if repo.is_dirty(untracked_files=True)
                    else "clean"
                )
            except Exception:
                repo_status = "status check failed"

            return {
                "success": True,
                "message": "File deleted successfully",
                "details": {
                    "file_path": str(test_file_path),
                    "verified": True,
                    "git_status": repo_status,
                },
            }

        except PermissionError as e:
            return {
                "success": False,
                "message": "Permission denied deleting file",
                "details": {
                    "error": str(e),
                    "file_path": str(test_file_path),
                    "error_type": "PermissionError",
                    "suggestion": "Check file system permissions for the file",
                },
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Error deleting file: {str(e)}",
                "details": {
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "file_path": str(test_file_path),
                },
            }

    def test_push(self, repo_id: int, git_auth_service) -> dict[str, Any]:
        """Test pushing a commit to the remote repository."""
        repository = git_repo_manager.get_repository(repo_id)
        if not repository:
            raise ValueError(f"Repository {repo_id} not found")

        repo = get_git_repo_by_id(repo_id)
        repo_path = Path(repo.working_dir)
        test_file_path = repo_path / ".cockpit_debug_test.txt"

        username, token, ssh_key_path = git_auth_service.resolve_credentials(repository)
        auth_type = repository.get("auth_type", "token")
        has_token_auth = bool(username and token)
        has_ssh_auth = bool(ssh_key_path)

        if auth_type == "ssh_key" and not has_ssh_auth:
            return {
                "success": False,
                "message": "SSH key authentication configured but no SSH key found",
                "details": {
                    "error": "Push requires SSH key credential",
                    "error_type": "AuthenticationRequired",
                    "suggestion": "Configure an SSH key credential for this repository to enable push operations",
                },
            }
        elif auth_type == "token" and not has_token_auth:
            return {
                "success": False,
                "message": "No credentials configured for push",
                "details": {
                    "error": "Push requires authentication credentials",
                    "error_type": "AuthenticationRequired",
                    "suggestion": "Configure a token credential for this repository to enable push operations",
                },
            }
        elif auth_type == "none":
            return {
                "success": False,
                "message": "Authentication is disabled for this repository",
                "details": {
                    "error": "Push requires authentication",
                    "error_type": "AuthenticationRequired",
                    "suggestion": "Set authentication type to 'Token' or 'SSH Key' to enable push operations",
                },
            }

        try:
            test_content = (
                f"Cockpit Debug Push Test\n"
                f"Timestamp: {datetime.now().isoformat()}\n"
                f"Repository: {repository['name']}\n"
            )
            test_file_path.write_text(test_content)

            try:
                repo.index.add([".cockpit_debug_test.txt"])
            except Exception as add_error:
                return {
                    "success": False,
                    "message": f"Failed to stage file: {str(add_error)}",
                    "details": {
                        "error": str(add_error),
                        "error_type": type(add_error).__name__,
                        "stage": "git_add",
                    },
                }

            commit_sha = None
            try:
                commit_message = f"Debug push test - {datetime.now().isoformat()}"
                with set_git_author(repository, repo):
                    commit = repo.index.commit(commit_message)
                commit_sha = commit.hexsha[:8]
            except Exception as commit_error:
                if "nothing to commit" in str(commit_error).lower():
                    return {
                        "success": False,
                        "message": "No changes to push (test file unchanged)",
                        "details": {
                            "error": str(commit_error),
                            "error_type": "NoChanges",
                            "suggestion": "The test file already exists with the same content. Use Write test first.",
                        },
                    }
                return {
                    "success": False,
                    "message": f"Failed to commit changes: {str(commit_error)}",
                    "details": {
                        "error": str(commit_error),
                        "error_type": type(commit_error).__name__,
                        "stage": "git_commit",
                    },
                }

            original_url = None
            try:
                origin = repo.remote("origin")
                original_url = list(origin.urls)[0]

                with set_ssl_env(repository):
                    with git_auth_service.setup_auth_environment(repository) as (
                        auth_url,
                        _username,
                        _token,
                        _ssh_key_path,
                    ):
                        if auth_type != "ssh_key":
                            origin.set_url(auth_url)

                        try:
                            push_info = origin.push(
                                refspec=f"{repository['branch']}:{repository['branch']}"
                            )

                            if auth_type != "ssh_key" and original_url:
                                try:
                                    origin.set_url(original_url)
                                except Exception:
                                    pass

                            if push_info and len(push_info) > 0:
                                push_result = push_info[0]
                                if push_result.flags & push_result.ERROR:
                                    return {
                                        "success": False,
                                        "message": f"Push failed: {push_result.summary}",
                                        "details": {
                                            "error": push_result.summary,
                                            "error_type": "PushError",
                                            "commit_sha": commit_sha,
                                            "suggestion": "Check repository permissions and credentials",
                                        },
                                    }
                                return {
                                    "success": True,
                                    "message": "Push test successful - changes pushed to remote",
                                    "details": {
                                        "commit_sha": commit_sha,
                                        "commit_message": commit_message,
                                        "branch": repository["branch"],
                                        "remote": "origin",
                                        "file_path": str(test_file_path),
                                        "push_summary": push_result.summary,
                                        "verified": True,
                                    },
                                }
                            return {
                                "success": False,
                                "message": "Push completed but no feedback received",
                                "details": {
                                    "error": "No push info returned",
                                    "error_type": "UnknownPushResult",
                                    "commit_sha": commit_sha,
                                },
                            }

                        except Exception as push_error:
                            if auth_type != "ssh_key" and original_url:
                                try:
                                    origin.set_url(original_url)
                                except Exception:
                                    pass

                            error_message = str(push_error)
                            if "permission denied" in error_message.lower() or "403" in error_message:
                                suggestion = "Authentication failed or insufficient permissions. Check that the token has write access."
                            elif "could not resolve host" in error_message.lower():
                                suggestion = "Network error: Cannot reach remote repository. Check network connectivity."
                            elif "authentication failed" in error_message.lower():
                                suggestion = "Credentials are invalid. Update the token in credential settings."
                            else:
                                suggestion = "Check repository configuration and network connectivity"

                            return {
                                "success": False,
                                "message": f"Failed to push: {error_message}",
                                "details": {
                                    "error": error_message,
                                    "error_type": type(push_error).__name__,
                                    "stage": "git_push",
                                    "commit_sha": commit_sha,
                                    "suggestion": suggestion,
                                },
                            }

            except Exception as remote_error:
                return {
                    "success": False,
                    "message": f"Failed to configure remote: {str(remote_error)}",
                    "details": {
                        "error": str(remote_error),
                        "error_type": type(remote_error).__name__,
                        "stage": "configure_remote",
                    },
                }

        except PermissionError as e:
            return {
                "success": False,
                "message": "Permission denied for file operations",
                "details": {
                    "error": str(e),
                    "file_path": str(test_file_path),
                    "error_type": "PermissionError",
                    "suggestion": "Check file system permissions for the repository directory",
                },
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Unexpected error during push test: {str(e)}",
                "details": {
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "file_path": str(test_file_path),
                },
            }

    def get_diagnostics(self, repo_id: int, git_auth_service) -> dict[str, Any]:
        """Return comprehensive diagnostic information for the repository."""
        repository = git_repo_manager.get_repository(repo_id)
        if not repository:
            raise ValueError(f"Repository {repo_id} not found")

        diagnostics: dict[str, Any] = {
            "repository_info": {
                "id": repository["id"],
                "name": repository["name"],
                "url": repository["url"],
                "branch": repository["branch"],
                "is_active": repository["is_active"],
                "verify_ssl": repository.get("verify_ssl", True),
            },
            "access_test": {},
            "file_system": {},
            "git_status": {},
            "ssl_info": {},
            "credentials": {},
            "push_capability": {},
        }

        try:
            repo = get_git_repo_by_id(repo_id)
            repo_path = Path(repo.working_dir)

            diagnostics["access_test"] = {
                "accessible": True,
                "path": str(repo_path),
                "exists": repo_path.exists(),
            }

            try:
                diagnostics["file_system"] = {
                    "readable": os.access(str(repo_path), os.R_OK),
                    "writable": os.access(str(repo_path), os.W_OK),
                    "executable": os.access(str(repo_path), os.X_OK),
                    "path": str(repo_path),
                }
            except Exception as e:
                diagnostics["file_system"] = {"error": str(e), "error_type": type(e).__name__}

            try:
                diagnostics["git_status"] = {
                    "is_dirty": repo.is_dirty(untracked_files=True),
                    "active_branch": repo.active_branch.name,
                    "head_commit": repo.head.commit.hexsha[:8] if repo.head.is_valid() else "no commits",
                    "remotes": [r.name for r in repo.remotes],
                    "has_origin": "origin" in [r.name for r in repo.remotes],
                }
            except Exception as e:
                diagnostics["git_status"] = {"error": str(e), "error_type": type(e).__name__}

        except Exception as e:
            diagnostics["access_test"] = {
                "accessible": False,
                "error": str(e),
                "error_type": type(e).__name__,
            }

        try:
            if not repository.get("verify_ssl", True):
                diagnostics["ssl_info"] = {
                    "verification": "disabled",
                    "note": "SSL verification is disabled for this repository",
                }
            else:
                diagnostics["ssl_info"] = {
                    "verification": "enabled",
                    "ssl_version": ssl.OPENSSL_VERSION,
                }
        except Exception as e:
            diagnostics["ssl_info"] = {"error": str(e), "error_type": type(e).__name__}

        try:
            username, token, ssh_key_path = git_auth_service.resolve_credentials(repository)
            auth_type = repository.get("auth_type", "token")

            diagnostics["credentials"] = {
                "credential_name": repository.get("credential_name", "none"),
                "auth_type": auth_type,
                "has_username": bool(username),
                "has_token": bool(token),
                "has_ssh_key": bool(ssh_key_path),
                "token_length": len(token) if token else 0,
                "authentication": "configured" if (username and token) or ssh_key_path else "none",
            }

            if auth_type == "ssh_key":
                has_credentials = bool(ssh_key_path)
            elif auth_type == "token":
                has_credentials = bool(username and token)
            else:
                has_credentials = False

            has_remote = False
            remote_url = "unknown"
            try:
                repo = get_git_repo_by_id(repo_id)
                if "origin" in [r.name for r in repo.remotes]:
                    has_remote = True
                    origin = repo.remote("origin")
                    remote_url = list(origin.urls)[0] if origin.urls else "unknown"
            except Exception:
                pass

            if has_credentials and has_remote:
                push_status, push_message = "ready", "Push capability is configured and ready"
            elif not has_credentials:
                push_status, push_message = "no_credentials", "Push requires authentication credentials"
            elif not has_remote:
                push_status, push_message = "no_remote", "No remote 'origin' configured"
            else:
                push_status, push_message = "unknown", "Push capability status unclear"

            diagnostics["push_capability"] = {
                "status": push_status,
                "message": push_message,
                "has_credentials": has_credentials,
                "has_remote": has_remote,
                "remote_url": remote_url,
                "can_push": has_credentials and has_remote,
            }

        except Exception as e:
            diagnostics["credentials"] = {"error": str(e), "error_type": type(e).__name__}
            diagnostics["push_capability"] = {
                "status": "error",
                "message": f"Failed to assess push capability: {str(e)}",
                "can_push": False,
            }

        return {"success": True, "repository_id": repo_id, "diagnostics": diagnostics}
```

---

### Updated `backend/service_factory.py` — add builder

Add at the end of `service_factory.py`:

```python
def build_git_debug_service():
    from services.git.debug_service import GitDebugService

    return GitDebugService()
```

---

### Updated `backend/dependencies.py` — add provider

Add at the end of `dependencies.py`:

```python
def get_git_debug_service():
    return service_factory.build_git_debug_service()
```

---

### Replacement `backend/routers/git/debug.py` (full file)

```python
"""
Git repository debug operations router - Debug and diagnostic endpoints.
Thin wrappers delegating to GitDebugService.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from core.auth import get_current_user
from dependencies import get_git_auth_service, get_git_debug_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/git-repositories", tags=["git-debug"])


@router.post("/{repo_id}/debug/read")
async def debug_read_test(
    repo_id: int,
    current_user: dict = Depends(get_current_user),
    debug_service=Depends(get_git_debug_service),
):
    """Debug operation: Test reading a file from the repository."""
    try:
        return debug_service.test_read(repo_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Debug read test failed for repo %s: %s", repo_id, e)
        return {
            "success": False,
            "message": f"Debug test failed: {str(e)}",
            "details": {"error": str(e), "error_type": type(e).__name__, "stage": "repository_access"},
        }


@router.post("/{repo_id}/debug/write")
async def debug_write_test(
    repo_id: int,
    current_user: dict = Depends(get_current_user),
    debug_service=Depends(get_git_debug_service),
):
    """Debug operation: Test writing a file to the repository."""
    try:
        return debug_service.test_write(repo_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Debug write test failed for repo %s: %s", repo_id, e)
        return {
            "success": False,
            "message": f"Debug test failed: {str(e)}",
            "details": {"error": str(e), "error_type": type(e).__name__, "stage": "repository_access"},
        }


@router.post("/{repo_id}/debug/delete")
async def debug_delete_test(
    repo_id: int,
    current_user: dict = Depends(get_current_user),
    debug_service=Depends(get_git_debug_service),
):
    """Debug operation: Test deleting the test file from the repository."""
    try:
        return debug_service.test_delete(repo_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Debug delete test failed for repo %s: %s", repo_id, e)
        return {
            "success": False,
            "message": f"Debug test failed: {str(e)}",
            "details": {"error": str(e), "error_type": type(e).__name__, "stage": "repository_access"},
        }


@router.post("/{repo_id}/debug/push")
async def debug_push_test(
    repo_id: int,
    current_user: dict = Depends(get_current_user),
    debug_service=Depends(get_git_debug_service),
    git_auth_service=Depends(get_git_auth_service),
):
    """Debug operation: Test pushing changes to the remote repository."""
    try:
        return debug_service.test_push(repo_id, git_auth_service)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Debug push test failed for repo %s: %s", repo_id, e)
        return {
            "success": False,
            "message": f"Debug test failed: {str(e)}",
            "details": {"error": str(e), "error_type": type(e).__name__, "stage": "repository_access"},
        }


@router.get("/{repo_id}/debug/diagnostics")
async def debug_diagnostics(
    repo_id: int,
    current_user: dict = Depends(get_current_user),
    debug_service=Depends(get_git_debug_service),
    git_auth_service=Depends(get_git_auth_service),
):
    """Get comprehensive diagnostic information for the repository."""
    try:
        return debug_service.get_diagnostics(repo_id, git_auth_service)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Debug diagnostics failed for repo %s: %s", repo_id, e)
        return {"success": False, "error": str(e), "error_type": type(e).__name__}
```

### Steps

1. Create `backend/services/git/debug_service.py` with the content above.
2. Append `build_git_debug_service` to `backend/service_factory.py`.
3. Append `get_git_debug_service` to `backend/dependencies.py`.
4. Replace `backend/routers/git/debug.py` with the thin-wrapper version above.
5. Verify: `wc -l backend/routers/git/debug.py` — should be ~80 lines.
6. Run `ruff check backend/services/git/debug_service.py backend/routers/git/debug.py`.
7. Test all 5 debug endpoints end-to-end.

---

## MEDIUM-5: Extract `GitVersionControlService` from `routers/git/version_control.py`

**What:** The `compare_commits` handler embeds ~120 lines of `difflib`/`SequenceMatcher` logic, and `get_commits` embeds cache read/write logic — both belong in a service.

**Why:** CLAUDE.md: "Business logic in routers" is an INCORRECT practice.

**Files changed / created:**
- `backend/services/git/version_control_service.py` — **new file**
- `backend/routers/git/version_control.py` — replace with thin wrappers
- `backend/service_factory.py` — add `build_git_version_control_service`
- `backend/dependencies.py` — add `get_git_version_control_service`

---

### New file: `backend/services/git/version_control_service.py`

```python
"""Git version control operations: branches, commits, diffs."""

from __future__ import annotations

import difflib
import logging
from typing import Any

from services.git.shared_utils import get_git_repo_by_id

logger = logging.getLogger(__name__)

_CACHE_CFG = {"enabled": True, "ttl_seconds": 600, "max_commits": 500}


class GitVersionControlService:
    """Encapsulates VCS operations: branch listing, commit log, and diff computation."""

    def get_branches(self, repo_id: int) -> list[dict[str, Any]]:
        """Return all branches with a flag indicating which is active."""
        repo = get_git_repo_by_id(repo_id)
        current_branch = repo.active_branch.name if repo.active_branch else None
        return [
            {"name": branch.name, "current": branch.name == current_branch}
            for branch in repo.branches
        ]

    def get_commits(
        self,
        repo_id: int,
        branch_name: str,
        cache_service=None,
    ) -> list[dict[str, Any]]:
        """Return commits for a branch, using cache when available."""
        repo = get_git_repo_by_id(repo_id)

        if branch_name not in [ref.name for ref in repo.refs]:
            raise ValueError(f"Branch '{branch_name}' not found")

        cache_key = f"repo:{repo_id}:commits:{branch_name}"
        if _CACHE_CFG.get("enabled", True) and cache_service:
            cached = cache_service.get(cache_key)
            if cached is not None:
                return cached

        limit = int(_CACHE_CFG.get("max_commits", 500))
        commits = [
            {
                "hash": commit.hexsha,
                "short_hash": commit.hexsha[:8],
                "message": commit.message.strip(),
                "author": {"name": commit.author.name, "email": commit.author.email},
                "date": commit.committed_datetime.isoformat(),
                "files_changed": len(commit.stats.files),
            }
            for commit in repo.iter_commits(branch_name, max_count=limit)
        ]

        if _CACHE_CFG.get("enabled", True) and cache_service:
            cache_service.set(cache_key, commits, int(_CACHE_CFG.get("ttl_seconds", 600)))

        return commits

    def compare_commits(
        self,
        repo_id: int,
        commit1: str,
        commit2: str,
        file_path: str,
    ) -> dict[str, Any]:
        """Compare a file between two commits and return unified diff + side-by-side data."""
        repo = get_git_repo_by_id(repo_id)

        commit_obj1 = repo.commit(commit1)
        commit_obj2 = repo.commit(commit2)

        try:
            file_content1 = (commit_obj1.tree / file_path).data_stream.read().decode("utf-8")
        except KeyError:
            file_content1 = ""

        try:
            file_content2 = (commit_obj2.tree / file_path).data_stream.read().decode("utf-8")
        except KeyError:
            file_content2 = ""

        lines1 = file_content1.splitlines(keepends=True)
        lines2 = file_content2.splitlines(keepends=True)

        diff_lines = [
            line.rstrip("\n")
            for line in difflib.unified_diff(lines1, lines2, n=3)
        ]

        additions = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
        deletions = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---"))

        lines1_list = file_content1.splitlines()
        lines2_list = file_content2.splitlines()

        file1_lines: list[dict] = []
        file2_lines: list[dict] = []

        matcher = difflib.SequenceMatcher(None, lines1_list, lines2_list)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                file1_lines += [{"line_number": i + 1, "content": lines1_list[i], "type": "equal"} for i in range(i1, i2)]
                file2_lines += [{"line_number": j + 1, "content": lines2_list[j], "type": "equal"} for j in range(j1, j2)]
            elif tag == "delete":
                file1_lines += [{"line_number": i + 1, "content": lines1_list[i], "type": "delete"} for i in range(i1, i2)]
            elif tag == "insert":
                file2_lines += [{"line_number": j + 1, "content": lines2_list[j], "type": "insert"} for j in range(j1, j2)]
            elif tag == "replace":
                file1_lines += [{"line_number": i + 1, "content": lines1_list[i], "type": "replace"} for i in range(i1, i2)]
                file2_lines += [{"line_number": j + 1, "content": lines2_list[j], "type": "replace"} for j in range(j1, j2)]

        return {
            "commit1": commit1[:8],
            "commit2": commit2[:8],
            "file_path": file_path,
            "diff_lines": diff_lines,
            "left_file": f"{file_path} ({commit1[:8]})",
            "right_file": f"{file_path} ({commit2[:8]})",
            "left_lines": file1_lines,
            "right_lines": file2_lines,
            "stats": {
                "additions": additions,
                "deletions": deletions,
                "changes": additions + deletions,
                "total_lines": len(diff_lines),
            },
        }
```

---

### Updated `backend/service_factory.py` — add builder

```python
def build_git_version_control_service():
    from services.git.version_control_service import GitVersionControlService

    return GitVersionControlService()
```

---

### Updated `backend/dependencies.py` — add provider

```python
def get_git_version_control_service():
    return service_factory.build_git_version_control_service()
```

---

### Replacement `backend/routers/git/version_control.py` (full file)

```python
"""
Git version control router - Git VCS operations like branches, commits, and diffs.
Thin wrappers delegating to GitVersionControlService.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from git import GitCommandError, InvalidGitRepositoryError

from core.auth import get_current_user
from core.safe_http_errors import raise_internal_server_error
from dependencies import get_cache_service, get_git_version_control_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/git/{repo_id}", tags=["git-version-control"])


@router.get("/branches")
async def get_branches(
    repo_id: int,
    current_user: dict = Depends(get_current_user),
    vc_service=Depends(get_git_version_control_service),
):
    """Get list of Git branches."""
    try:
        return vc_service.get_branches(repo_id)
    except (InvalidGitRepositoryError, GitCommandError) as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Git repository not found or invalid: {str(e)}",
        )
    except Exception as e:
        raise_internal_server_error(logger, "Git branches error: ", e)


@router.get("/commits/{branch_name}")
async def get_commits(
    repo_id: int,
    branch_name: str,
    current_user: dict = Depends(get_current_user),
    cache_service=Depends(get_cache_service),
    vc_service=Depends(get_git_version_control_service),
):
    """Get commits for a specific branch."""
    try:
        return vc_service.get_commits(repo_id, branch_name, cache_service)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise_internal_server_error(logger, "Failed to get commits: ", e)


@router.post("/diff")
async def compare_commits(
    repo_id: int,
    request: dict,
    current_user: dict = Depends(get_current_user),
    vc_service=Depends(get_git_version_control_service),
):
    """Compare files between two Git commits."""
    try:
        commit1 = request.get("commit1")
        commit2 = request.get("commit2")
        file_path = request.get("file_path")

        if not all([commit1, commit2, file_path]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing required parameters: commit1, commit2, file_path",
            )

        return vc_service.compare_commits(repo_id, commit1, commit2, file_path)

    except HTTPException:
        raise
    except Exception as e:
        raise_internal_server_error(logger, "Failed to compare commits: ", e)
```

### Steps

1. Create `backend/services/git/version_control_service.py` with the content above.
2. Append `build_git_version_control_service` to `backend/service_factory.py`.
3. Append `get_git_version_control_service` to `backend/dependencies.py`.
4. Replace `backend/routers/git/version_control.py` with the thin-wrapper version above.
5. Verify: `wc -l backend/routers/git/version_control.py` — should be ~65 lines.
6. Run `ruff check backend/services/git/version_control_service.py backend/routers/git/version_control.py`.
7. Test all 3 endpoints: branches list, commits list (with and without cache), diff between two commits.

---

## MEDIUM-6: Fix Repository DI Bypass in `GitRepositoryRepository`

**What:** The four custom methods (`get_by_name`, `get_by_category`, `get_all_active`, `name_exists`) call `get_db_session()` directly instead of using `BaseRepository._db_session(db)`, bypassing FastAPI's dependency injection.

**Why:** CLAUDE.md: "NEVER bypass repository layer" (and by extension, NEVER bypass the DI-managed session).

**Files changed:**
- `backend/repositories/git/git_repository_repository.py`

### Code before (full file)

```python
"""Repository for git repository operations."""

from typing import List, Optional

from core.database import get_db_session
from core.models import GitRepository
from repositories.base import BaseRepository


class GitRepositoryRepository(BaseRepository[GitRepository]):
    """Repository for managing git repositories."""

    def __init__(self):
        super().__init__(GitRepository)

    def get_by_name(self, name: str) -> Optional[GitRepository]:
        db = get_db_session()
        try:
            return db.query(GitRepository).filter(GitRepository.name == name).first()
        finally:
            db.close()

    def get_by_category(
        self, category: str, active_only: bool = True
    ) -> List[GitRepository]:
        db = get_db_session()
        try:
            query = db.query(GitRepository).filter(GitRepository.category == category)
            if active_only:
                query = query.filter(GitRepository.is_active)
            return query.all()
        finally:
            db.close()

    def get_all_active(self) -> List[GitRepository]:
        db = get_db_session()
        try:
            return db.query(GitRepository).filter(GitRepository.is_active).all()
        finally:
            db.close()

    def name_exists(self, name: str) -> bool:
        db = get_db_session()
        try:
            return (
                db.query(GitRepository).filter(GitRepository.name == name).count() > 0
            )
        finally:
            db.close()
```

### Code after (full file)

```python
"""Repository for git repository operations."""

from typing import List, Optional

from sqlalchemy.orm import Session

from core.models import GitRepository
from repositories.base import BaseRepository


class GitRepositoryRepository(BaseRepository[GitRepository]):
    """Repository for managing git repositories."""

    def __init__(self):
        super().__init__(GitRepository)

    def get_by_name(self, name: str, db: Optional[Session] = None) -> Optional[GitRepository]:
        with self._db_session(db) as s:
            return s.query(GitRepository).filter(GitRepository.name == name).first()

    def get_by_category(
        self, category: str, active_only: bool = True, db: Optional[Session] = None
    ) -> List[GitRepository]:
        with self._db_session(db) as s:
            query = s.query(GitRepository).filter(GitRepository.category == category)
            if active_only:
                query = query.filter(GitRepository.is_active)
            return query.all()

    def get_all_active(self, db: Optional[Session] = None) -> List[GitRepository]:
        with self._db_session(db) as s:
            return s.query(GitRepository).filter(GitRepository.is_active).all()

    def name_exists(self, name: str, db: Optional[Session] = None) -> bool:
        with self._db_session(db) as s:
            return s.query(GitRepository).filter(GitRepository.name == name).count() > 0
```

**Key changes:**
- Removed `from core.database import get_db_session` import.
- Added `from sqlalchemy.orm import Session` import.
- Each method now accepts an optional `db: Optional[Session] = None` parameter.
- Each method uses `with self._db_session(db) as s:` (from `BaseRepository`) instead of calling `get_db_session()` directly.
- No external callers need to change — the `db` parameter is optional and defaults to `None` (falls back to the same `get_db_session()` path via `BaseRepository._db_session`).

### Steps

1. Open `backend/repositories/git/git_repository_repository.py`.
2. Replace the entire file contents with the "after" version above.
3. Verify: `grep -n "get_db_session" backend/repositories/git/git_repository_repository.py` → should return nothing.
4. Run `ruff check backend/repositories/git/git_repository_repository.py`.
5. No call-site changes needed — existing callers omit `db` and the fallback path is identical.

---

## MEDIUM-7: Rename `InventoryPersistenceService` → `InventoryService`

**What:** The class name `InventoryPersistenceService` is misleading — "persistence" is an implementation detail of every service that touches a database. The class is simply the inventory service for the Nautobot source. Rename to `InventoryService`.

**Why:** CLAUDE.md naming conventions and no-god-object principle. The word "Persistence" in a service name implies the service is the persistence layer, but it is a business service sitting above `InventoryRepository`.

**Files changed (7 total):**

| File | Change |
|------|--------|
| `backend/services/sources/nautobot/persistence_service.py` | Rename class |
| `backend/dependencies.py` | Update import, type hints, function name |
| `backend/service_factory.py` | Update import, function name, return type |
| `backend/routers/sources/nautobot/ops.py` | Update import, type hints |
| `backend/routers/sources/nautobot/crud.py` | Update import, type hints |
| `backend/services/sources/nautobot/source_service.py` | Update import, type hint |

---

### 1. `backend/services/sources/nautobot/persistence_service.py`

**Before:**
```python
class InventoryPersistenceService:
    """Manages Ansible inventory configurations in PostgreSQL database."""
```

**After:**
```python
class InventoryService:
    """Manages Ansible inventory configurations in PostgreSQL database."""
```

> The filename `persistence_service.py` can stay as-is to avoid breaking any cache references. Only the class name changes.

---

### 2. `backend/dependencies.py`

**Before:**
```python
from services.sources.nautobot.persistence_service import InventoryPersistenceService


def get_inventory_persistence_service(
    db: Session = Depends(get_db),
) -> InventoryPersistenceService:
    return service_factory.build_inventory_persistence_service(db)
```

**After:**
```python
from services.sources.nautobot.persistence_service import InventoryService


def get_inventory_service(
    db: Session = Depends(get_db),
) -> InventoryService:
    return service_factory.build_inventory_service(db)
```

> **Note:** `get_inventory_persistence_service` is referenced in `ops.py` and `crud.py` — those are updated below. After updating all call sites, the old name is gone.

---

### 3. `backend/service_factory.py`

**Before:**
```python
from services.sources.nautobot.persistence_service import InventoryPersistenceService
...
def build_inventory_persistence_service(db: Session) -> InventoryPersistenceService:
    return InventoryPersistenceService(repository=InventoryRepository(db))
```

**After:**
```python
from services.sources.nautobot.persistence_service import InventoryService
...
def build_inventory_service(db: Session) -> InventoryService:
    return InventoryService(repository=InventoryRepository(db))
```

Also update the reference inside `build_nautobot_source_service`:

**Before:**
```python
    persistence = build_inventory_persistence_service(db) if db is not None else None
```

**After:**
```python
    persistence = build_inventory_service(db) if db is not None else None
```

---

### 4. `backend/routers/sources/nautobot/ops.py`

**Before (lines 12–14, 26, 36, 42, 49, 62, 170, 217, 288):**
```python
from dependencies import get_inventory_persistence_service
...
from services.sources.nautobot.persistence_service import InventoryPersistenceService
...
    persistence: InventoryPersistenceService | None = None,
...
    persistence: InventoryPersistenceService = Depends(get_inventory_persistence_service),
# (repeated at lines 62, 170, 217, 288)
```

**After:**
```python
from dependencies import get_inventory_service
...
from services.sources.nautobot.persistence_service import InventoryService
...
    persistence: InventoryService | None = None,
...
    persistence: InventoryService = Depends(get_inventory_service),
# (repeated at all 5 occurrences)
```

---

### 5. `backend/routers/sources/nautobot/crud.py`

**Before (lines 14, 23, 33, 74, 96, 112, 132, 195, 251, 274, 313):**
```python
from dependencies import get_inventory_persistence_service
...
from services.sources.nautobot.persistence_service import InventoryPersistenceService
...
    persistence: InventoryPersistenceService = Depends(get_inventory_persistence_service),
# (repeated at lines 74, 96, 112, 132, 195, 251, 274, 313)
```

**After:**
```python
from dependencies import get_inventory_service
...
from services.sources.nautobot.persistence_service import InventoryService
...
    persistence: InventoryService = Depends(get_inventory_service),
# (repeated at all 9 occurrences)
```

---

### 6. `backend/services/sources/nautobot/source_service.py`

**Before:**
```python
from services.sources.nautobot.persistence_service import InventoryPersistenceService
...
        persistence_service: InventoryPersistenceService | None = None,
...
        self._persistence_service = persistence_service
```

**After:**
```python
from services.sources.nautobot.persistence_service import InventoryService
...
        persistence_service: InventoryService | None = None,
...
        self._persistence_service = persistence_service
```

### Steps

1. In `persistence_service.py`: rename class `InventoryPersistenceService` → `InventoryService`.
2. Run: `grep -rn "InventoryPersistenceService" backend/ --include="*.py"` — get the full list of occurrences.
3. Update `service_factory.py` (import + two function names + internal call).
4. Update `dependencies.py` (import + function name + return type).
5. Update `routers/sources/nautobot/ops.py` (import + all 5 type hint occurrences + Depends call names).
6. Update `routers/sources/nautobot/crud.py` (import + all 9 type hint occurrences + Depends call names).
7. Update `services/sources/nautobot/source_service.py` (import + type hint).
8. Verify: `grep -rn "InventoryPersistenceService\|get_inventory_persistence_service\|build_inventory_persistence_service" backend/ --include="*.py"` → must return nothing.
9. Run `ruff check backend/` — should pass.
10. Start the backend and verify `/sources/nautobot/` endpoints still function.
