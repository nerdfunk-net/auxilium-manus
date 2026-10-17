"""
Git file operations router — thin delegates to GitFileService.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from core.auth import get_current_user, require_permission
from dependencies import get_git_file_service
from services.git.file_service import GitFileService

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/git/{repo_id}",
    tags=["git-files"],
    dependencies=[Depends(require_permission("git.files", "read"))],
)


@router.get("/file-content-parsed")
def get_file_content_parsed(
    repo_id: int,
    path: str,
    current_user: dict = Depends(get_current_user),
    git_file_service: GitFileService = Depends(get_git_file_service),
):
    return git_file_service.get_file_content_parsed(
        repo_id, path, username=current_user.get("username")
    )
