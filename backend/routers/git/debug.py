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


def _debug_error(e: Exception, repo_id: int, stage: str = "repository_access") -> dict:
    return {
        "success": False,
        "message": f"Debug test failed: {str(e)}",
        "details": {
            "error": str(e),
            "error_type": type(e).__name__,
            "stage": stage,
        },
    }


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
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.error("Debug read test failed for repo %s: %s", repo_id, e)
        return _debug_error(e, repo_id)


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
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.error("Debug write test failed for repo %s: %s", repo_id, e)
        return _debug_error(e, repo_id)


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
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.error("Debug delete test failed for repo %s: %s", repo_id, e)
        return _debug_error(e, repo_id)


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
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.error("Debug push test failed for repo %s: %s", repo_id, e)
        return _debug_error(e, repo_id)


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
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.error("Debug diagnostics failed for repo %s: %s", repo_id, e)
        return {"success": False, "error": str(e), "error_type": type(e).__name__}
