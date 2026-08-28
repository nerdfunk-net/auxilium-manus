"""Device and content-search preview operations for a configured git repository."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.domain_exceptions import DomainError
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from services.git.content_search_service import GitContentSearchService
from services.git.device_service import GitDeviceService
from services.git.repository_service import GitRepositoryService
from services.git.sync import clone_or_pull
from services.network.cisco_config_parsing import parse_cisco_config_text

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/git/{repo_id}", tags=["git-devices"])


class GitDevicePreviewRequest(BaseModel):
    filename_pattern: str
    directory: str = ""


class GitDevicePreviewResponse(BaseModel):
    devices: list[dict[str, Any]]
    total_count: int
    files_read: int


class GitContentSearchPreviewRequest(BaseModel):
    directory: str = ""
    file_filter: str = ""
    recursive: bool = True
    include_history: bool = False
    search_text: str
    case_sensitive: bool = False


class GitContentSearchPreviewMatch(BaseModel):
    file_path: str
    line_content: str
    hostname: str | None
    commit: str | None


class GitContentSearchPreviewResponse(BaseModel):
    matches: list[GitContentSearchPreviewMatch]
    total_matches: int
    files_scanned: int


def _load_repository(repo_id: int, db: Session) -> dict[str, Any]:
    repository = GitRepositoryService(db).get_repository(repo_id)
    if repository is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")
    return repository


@router.post(
    "/preview-devices",
    response_model=GitDevicePreviewResponse,
    dependencies=[Depends(require_permission("git.operations", "read"))],
)
async def preview_git_devices(
    repo_id: int,
    request: GitDevicePreviewRequest,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GitDevicePreviewResponse:
    pattern = request.filename_pattern.strip()
    if not pattern:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="filename_pattern is required"
        )

    repository = _load_repository(repo_id, db)
    service = GitDeviceService()
    loop = asyncio.get_running_loop()
    try:
        devices, files_read = await loop.run_in_executor(
            None, lambda: service.fetch_devices(repository, pattern, request.directory)
        )
        return GitDevicePreviewResponse(
            devices=devices, total_count=len(devices), files_read=files_read
        )
    except (HTTPException, DomainError):
        raise
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to preview git devices: ", exc)


@router.post(
    "/content-search-preview",
    response_model=GitContentSearchPreviewResponse,
    dependencies=[Depends(require_permission("git.operations", "read"))],
)
async def preview_git_content_search(
    repo_id: int,
    request: GitContentSearchPreviewRequest,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GitContentSearchPreviewResponse:
    if not request.search_text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="search_text is required"
        )

    repository = _load_repository(repo_id, db)
    loop = asyncio.get_running_loop()
    try:
        repo_dir = await loop.run_in_executor(None, lambda: clone_or_pull(repository))
        search_service = GitContentSearchService()
        matches, files_scanned = await loop.run_in_executor(
            None,
            lambda: search_service.search(
                repo_dir,
                directory=request.directory,
                file_filter=request.file_filter,
                recursive=request.recursive,
                include_history=request.include_history,
                search_text=request.search_text,
                case_sensitive=request.case_sensitive,
            ),
        )

        preview_matches: list[GitContentSearchPreviewMatch] = []
        for match in matches:
            hostname: str | None = None
            try:
                parsed = parse_cisco_config_text(match.content, None)
                candidate = str(parsed.get("hostname") or "").strip()
                hostname = candidate or None
            except ValueError:
                hostname = None
            preview_matches.append(
                GitContentSearchPreviewMatch(
                    file_path=match.file_path,
                    line_content=match.line_content,
                    hostname=hostname,
                    commit=match.commit,
                )
            )

        return GitContentSearchPreviewResponse(
            matches=preview_matches,
            total_matches=len(preview_matches),
            files_scanned=files_scanned,
        )
    except (HTTPException, DomainError):
        raise
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to preview git content search: ", exc)
