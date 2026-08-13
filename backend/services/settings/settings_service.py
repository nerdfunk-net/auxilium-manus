from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from core.models.settings import Setting
from core.safe_urls import UnsafeURLError, validate_outbound_http_url
from models.settings import (
    SettingCreate,
    SettingListResponse,
    SettingResponse,
    SettingUpdate,
)
from repositories.settings_repository import SettingsRepository
from services.settings.exceptions import SourceConfigError
from services.settings.source_keys import (
    SourceType,
    build_source_key,
    ensure_value_source_id,
    parse_source_key,
)

logger = logging.getLogger(__name__)


_TOKEN_SOURCE_TYPES = frozenset({"nautobot", "git"})


def _redact_source_token(key: str, value: dict[str, Any] | None) -> dict[str, Any]:
    parsed = parse_source_key(key)
    raw = dict(value or {})
    if parsed is None or parsed[0] not in _TOKEN_SOURCE_TYPES:
        return raw
    token_configured = bool(str(raw.get("token") or "").strip())
    redacted = dict(raw)
    redacted["token"] = ""
    redacted["token_configured"] = token_configured
    return redacted


def _to_response(setting: Setting) -> SettingResponse:
    return SettingResponse(
        id=setting.id,
        key=setting.key,
        value=_redact_source_token(setting.key, setting.value),
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

    def get_source_config(self, source_type: SourceType, source_id: str) -> dict[str, Any]:
        """Load a typed source setting and return its value with ``source_id`` set.

        Router-facing: raises ``HTTPException`` directly, matching the 4
        call sites in routers/sources/git/ops.py that let it propagate
        uncaught to FastAPI's handler. Workflow-step executors must use
        ``get_source_config_for_step`` instead — see its docstring.
        """
        source_id = source_id.strip()
        if not source_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{source_type}_source_id is required",
            )
        try:
            setting_key = build_source_key(source_type, source_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        setting = self.repo.get_by_key(setting_key)
        if setting is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{source_type.title()} source '{source_id}' not found in settings",
            )
        return {**(setting.value or {}), "source_id": source_id}

    def get_source_config_for_step(self, source_type: SourceType, source_id: str) -> dict[str, Any]:
        """Worker-safe equivalent of ``get_source_config``.

        Workflow-step executors run in the Hatchet worker, not a FastAPI
        request, and must raise ``ValueError`` for configuration problems
        (doc/WORKFLOW-STEPS.md) rather than importing/catching
        ``fastapi.HTTPException`` — see doc/FABLE-ANALYSIS.md §3.1.
        """
        try:
            return self.get_source_config(source_type, source_id)
        except HTTPException as exc:
            raise SourceConfigError(str(exc.detail)) from exc

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
            incoming = dict(data.value)
            parsed = parse_source_key(key)
            if parsed is not None and parsed[0] in _TOKEN_SOURCE_TYPES:
                incoming_token = str(incoming.get("token") or "").strip()
                if not incoming_token:
                    existing = setting.value or {}
                    incoming["token"] = existing.get("token", "")
            fields["value"] = self._normalize_source_value(key, incoming)
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
        value = dict(value)
        value.pop("token_configured", None)
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

        validated = SettingsService._validate_source_url(source_type, value)
        return ensure_value_source_id(validated, source_type=source_type, source_id=source_id)

    @staticmethod
    def _validate_source_url(source_type: SourceType, value: dict) -> dict:
        """Validate outbound HTTP URLs for ISE/Nautobot source settings."""
        if source_type not in ("nautobot", "ise"):
            return value
        raw_url = value.get("url")
        if raw_url is None:
            return value
        try:
            safe_url = validate_outbound_http_url(str(raw_url), resolve_dns=True)
        except UnsafeURLError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        return {**value, "url": safe_url}
