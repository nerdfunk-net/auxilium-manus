"""
Git file operations router — thin delegates to GitFileService.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from core.auth import get_current_user
from dependencies import get_cache_service
from services.git.file_service import GitFileService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/git/{repo_id}", tags=["git-files"])

_git_file_service = GitFileService()


@router.get("/files/search")
async def search_repository_files(
    repo_id: int,
    query: str = "",
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
):
    return _git_file_service.search_files(repo_id, query, limit)


@router.get("/files/{commit_hash}/commit")
async def get_files(
    repo_id: int,
    commit_hash: str,
    file_path: str = None,
    current_user: dict = Depends(get_current_user),
):
    return _git_file_service.get_commit_files(repo_id, commit_hash, file_path)


@router.get("/files/{file_path:path}/history")
async def get_file_history(
    repo_id: int,
    file_path: str,
    current_user: dict = Depends(get_current_user),
):
    return _git_file_service.get_file_last_commit(repo_id, file_path)


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


@router.get("/file-content")
async def get_file_content(
    repo_id: int,
    path: str,
    current_user: dict = Depends(get_current_user),
):
    content = _git_file_service.get_file_content(
        repo_id, path, username=current_user.get("username")
    )
    return PlainTextResponse(content=content)


@router.get("/file-content-parsed")
async def get_file_content_parsed(
    repo_id: int,
    path: str,
    current_user: dict = Depends(get_current_user),
):
    return _git_file_service.get_file_content_parsed(
        repo_id, path, username=current_user.get("username")
    )


@router.get("/tree")
async def get_directory_tree(
    repo_id: int,
    path: str = "",
    current_user: dict = Depends(get_current_user),
):
    return _git_file_service.get_directory_tree(repo_id, path)


@router.get("/directory")
async def get_directory_files(
    repo_id: int,
    path: str = "",
    current_user: dict = Depends(get_current_user),
):
    return _git_file_service.get_directory_files(repo_id, path)


@router.get("/csv-files")
async def list_csv_files(
    repo_id: int,
    query: str = "",
    limit: int = 200,
    current_user: dict = Depends(get_current_user),
):
    return _git_file_service.list_csv_files(repo_id, query, limit)


@router.get("/csv-headers")
async def get_csv_headers(
    repo_id: int,
    path: str,
    delimiter: str = ",",
    quote_char: str = '"',
    current_user: dict = Depends(get_current_user),
):
    return _git_file_service.get_csv_headers(repo_id, path, delimiter, quote_char)
