"""Git source operations — preview devices from a configured git repository."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from models.sources_git import (
    GitSourceTestConnectionRequest,
    GitSourceTestConnectionResponse,
)
from services.settings.settings_service import SettingsService
from services.sources.git.git_content_search_service import GitContentSearchService
from services.sources.git.git_source_service import (
    GitDeviceService,
    clone_or_pull,
    remove_and_clone,
)
from services.sources.git.git_source_service import (
    test_connection as test_git_source_connection,
)
from workflow_steps.common.cisco_config_parsing import parse_cisco_config_text

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
) -> GitSourceTestConnectionResponse:
    """Test Git connectivity using form values (does not require a saved source)."""
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: test_git_source_connection(
                url=request.url,
                branch=request.branch,
                username=request.username,
                token=request.token,
                verify_ssl=request.verify_ssl,
            ),
        )
        return GitSourceTestConnectionResponse(**result)
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
    logger.info(
        "[DEBUG] preview_git_devices ENTER — source_id=%r pattern=%r",
        source_id,
        request.filename_pattern,
    )

    if not request.filename_pattern.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="filename_pattern is required",
        )

    source_config = SettingsService(db).get_source_config("git", source_id)
    logger.info("[DEBUG] preview_git_devices — setting found, calling fetch_devices in executor")

    try:
        service = GitDeviceService()
        pattern = request.filename_pattern.strip()
        loop = asyncio.get_event_loop()
        devices, files_read = await loop.run_in_executor(
            None, lambda: service.fetch_devices(source_config, pattern)
        )
        logger.info(
            "[DEBUG] preview_git_devices — executor returned %d device(s), %d file(s)",
            len(devices),
            files_read,
        )
        return GitPreviewResponse(
            devices=devices,
            total_count=len(devices),
            files_read=files_read,
        )
    except ValueError as exc:
        logger.info("[DEBUG] preview_git_devices — ValueError: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.info("[DEBUG] preview_git_devices — unexpected exception: %s", exc)
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

    source_config = SettingsService(db).get_source_config("git", request.git_source_id)

    try:
        loop = asyncio.get_event_loop()
        repo_dir = await loop.run_in_executor(None, lambda: clone_or_pull(source_config))

        search_service = GitContentSearchService()
        matches, files_scanned = await loop.run_in_executor(
            None,
            lambda: search_service.search(
                repo_dir,
                source_config,
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
    source_config = SettingsService(db).get_source_config("git", request.git_source_id)
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: clone_or_pull(source_config))
        sid = source_config["source_id"]
        return {"success": True, "message": f"Git source '{sid}' pulled successfully"}
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
    source_config = SettingsService(db).get_source_config("git", request.git_source_id)
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: remove_and_clone(source_config))
        sid = source_config["source_id"]
        msg = f"Git source '{sid}' removed and re-cloned successfully"
        return {"success": True, "message": msg}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to remove and clone git source", exc)
