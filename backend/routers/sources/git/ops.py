"""Git source operations — preview devices from a configured git repository."""

from __future__ import annotations

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
from models.sources_git import (
    GitSourceTestConnectionRequest,
    GitSourceTestConnectionResponse,
)
from services.sources.git.git_source_service import (
    preview_content_search_from_source,
    preview_devices_from_source,
    pull_from_source,
    remove_and_clone_from_source,
    test_connection_from_request,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sources/git", tags=["sources-git"])


class GitPreviewRequest(BaseModel):
    git_source_id: str
    filename_pattern: str


class GitPreviewResponse(BaseModel):
    devices: list[dict[str, Any]]
    total_count: int
    files_read: int


class GitContentSearchPreviewRequest(BaseModel):
    git_source_id: str
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


class GitSourceActionRequest(BaseModel):
    git_source_id: str


@router.post(
    "/test-connection",
    response_model=GitSourceTestConnectionResponse,
    dependencies=[Depends(require_permission("sources.git", "read"))],
)
async def test_connection(
    request: GitSourceTestConnectionRequest,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GitSourceTestConnectionResponse:
    """Test Git connectivity using form values or a saved source."""
    try:
        result = await test_connection_from_request(request, db)
        return GitSourceTestConnectionResponse(**result)
    except (HTTPException, DomainError):
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Git test connection failed: ", exc)


@router.post(
    "/preview",
    response_model=GitPreviewResponse,
    dependencies=[Depends(require_permission("sources.git", "read"))],
)
async def preview_git_devices(
    request: GitPreviewRequest,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GitPreviewResponse:
    source_id = request.git_source_id.strip()
    pattern = request.filename_pattern.strip()
    if not pattern:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="filename_pattern is required",
        )

    try:
        devices, files_read = await preview_devices_from_source(source_id, pattern, db)
        return GitPreviewResponse(
            devices=devices,
            total_count=len(devices),
            files_read=files_read,
        )
    except (HTTPException, DomainError):
        raise
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to preview git source: ", exc)


@router.post(
    "/content-search-preview",
    response_model=GitContentSearchPreviewResponse,
    dependencies=[Depends(require_permission("sources.git", "read"))],
)
async def preview_git_content_search(
    request: GitContentSearchPreviewRequest,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GitContentSearchPreviewResponse:
    if not request.search_text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="search_text is required",
        )

    try:
        matches, total_matches, files_scanned = await preview_content_search_from_source(
            source_id=request.git_source_id,
            directory=request.directory,
            file_filter=request.file_filter,
            recursive=request.recursive,
            include_history=request.include_history,
            search_text=request.search_text,
            case_sensitive=request.case_sensitive,
            db=db,
        )
        return GitContentSearchPreviewResponse(
            matches=[GitContentSearchPreviewMatch(**match) for match in matches],
            total_matches=total_matches,
            files_scanned=files_scanned,
        )
    except (HTTPException, DomainError):
        raise
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to preview git content search: ", exc)


@router.post(
    "/pull",
    dependencies=[Depends(require_permission("sources.git", "execute"))],
)
async def pull_git_source(
    request: GitSourceActionRequest,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Pull latest changes for a git source (clone if not yet cloned)."""
    try:
        sid = await pull_from_source(request.git_source_id, db)
        return {"success": True, "message": f"Git source '{sid}' pulled successfully"}
    except (HTTPException, DomainError):
        raise
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to pull git source", exc)


@router.post(
    "/remove-and-clone",
    dependencies=[Depends(require_permission("sources.git", "execute"))],
)
async def remove_and_clone_git_source(
    request: GitSourceActionRequest,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Remove existing local copy of a git source and clone fresh."""
    try:
        sid = await remove_and_clone_from_source(request.git_source_id, db)
        msg = f"Git source '{sid}' removed and re-cloned successfully"
        return {"success": True, "message": msg}
    except (HTTPException, DomainError):
        raise
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to remove and clone git source", exc)
