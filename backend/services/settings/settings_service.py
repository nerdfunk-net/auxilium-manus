from __future__ import annotations

import logging

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from core.models.settings import Setting
from models.settings import (
    SettingCreate,
    SettingListResponse,
    SettingResponse,
    SettingUpdate,
)
from repositories.settings_repository import SettingsRepository
from services.settings.source_keys import (
    ensure_value_source_id,
    parse_source_key,
)

logger = logging.getLogger(__name__)


def _to_response(setting: Setting) -> SettingResponse:
    return SettingResponse(
        id=setting.id,
        key=setting.key,
        value=setting.value,
        description=setting.description,
        created_at=setting.created_at,
        updated_at=setting.updated_at,
    )


class SettingsService:
    def __init__(self, db: Session) -> None:
        self.repo = SettingsRepository(db)

    def list_settings(self, *, key_prefix: str | None = None) -> SettingListResponse:
        rows = self.repo.list_all(key_prefix=key_prefix)
        settings = [_to_response(row) for row in rows]
        return SettingListResponse(settings=settings, total=len(settings))

    def get_setting(self, key: str) -> SettingResponse:
        setting = self.repo.get_by_key(key)
        if setting is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Setting '{key}' not found",
            )
        return _to_response(setting)

    def create_setting(self, data: SettingCreate) -> SettingResponse:
        if self.repo.get_by_key(data.key) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Setting '{data.key}' already exists",
            )

        value = self._normalize_source_value(data.key, data.value)

        logger.info("Creating setting key=%s", data.key)
        setting = self.repo.create(
            key=data.key,
            value=value,
            description=data.description,
        )
        return _to_response(setting)

    def update_setting(self, key: str, data: SettingUpdate) -> SettingResponse:
        setting = self.repo.get_by_key(key)
        if setting is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Setting '{key}' not found",
            )

        fields: dict = {}
        if data.value is not None:
            fields["value"] = self._normalize_source_value(key, data.value)
        if data.description is not None:
            fields["description"] = data.description

        if not fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields to update",
            )

        logger.info("Updating setting key=%s", key)
        updated = self.repo.update(setting, fields)
        return _to_response(updated)

    def delete_setting(self, key: str) -> None:
        setting = self.repo.get_by_key(key)
        if setting is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Setting '{key}' not found",
            )
        logger.info("Deleting setting key=%s", key)
        self.repo.delete(setting)

    @staticmethod
    def _normalize_source_value(key: str, value: dict) -> dict:
        parsed = parse_source_key(key)
        if parsed is None:
            return value

        source_type, source_id = parsed
        body_source_id = value.get("source_id")
        if isinstance(body_source_id, str) and body_source_id.strip():
            normalized_body_id = body_source_id.strip().lower()
            if normalized_body_id != source_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"source_id in value ('{normalized_body_id}') must match "
                        f"the key suffix ('{source_id}')"
                    ),
                )

        return ensure_value_source_id(value, source_type=source_type, source_id=source_id)
