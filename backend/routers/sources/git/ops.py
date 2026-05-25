"""Git source operations — preview devices from a configured git repository."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.auth import get_current_user
from core.database import get_db
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from repositories.settings_repository import SettingsRepository
from services.settings.source_keys import build_source_key
from services.sources.git.git_source_service import GitDeviceService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sources/git", tags=["sources-git"])


class GitPreviewRequest(BaseModel):
    git_source_id: str
    filename_pattern: str


class GitPreviewResponse(BaseModel):
    devices: list[dict[str, Any]]
    total_count: int
    files_read: int


@router.post("/preview", response_model=GitPreviewResponse)
async def preview_git_devices(
    request: GitPreviewRequest,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GitPreviewResponse:
    source_id = request.git_source_id.strip()
    logger.info("[DEBUG] preview_git_devices ENTER — source_id=%r pattern=%r", source_id, request.filename_pattern)

    if not source_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="git_source_id is required",
        )
    if not request.filename_pattern.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="filename_pattern is required",
        )

    setting_key = build_source_key("git", source_id)
    setting = SettingsRepository(db).get_by_key(setting_key)
    if setting is None:
        logger.info("[DEBUG] preview_git_devices — setting NOT FOUND for key=%r", setting_key)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Git source '{source_id}' not found in settings",
        )
    logger.info("[DEBUG] preview_git_devices — setting found, calling fetch_devices in executor")

    source_config: dict[str, Any] = {
        **(setting.value or {}),
        "source_id": source_id,
    }

    try:
        service = GitDeviceService()
        pattern = request.filename_pattern.strip()
        loop = asyncio.get_event_loop()
        devices, files_read = await loop.run_in_executor(
            None, lambda: service.fetch_devices(source_config, pattern)
        )
        logger.info("[DEBUG] preview_git_devices — executor returned %d device(s), %d file(s)", len(devices), files_read)
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
