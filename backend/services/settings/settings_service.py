from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from core.domain_exceptions import ConflictError, DomainError, NotFoundError, ValidationFailedError
from core.models.settings import Setting
from core.safe_urls import UnsafeURLError, validate_outbound_http_url
from models.settings import (
    SettingCreate,
    SettingListResponse,
    SettingResponse,
    SettingUpdate,
)
from repositories.settings_repository import SettingsRepository
from services.credentials.credentials_service import CredentialsService
from services.credentials.source_credentials import SourceCredentialError, assert_global_credential
from services.settings.exceptions import SourceConfigError
from services.settings.source_keys import (
    SourceType,
    build_source_key,
    ensure_value_source_id,
    parse_source_key,
)

logger = logging.getLogger(__name__)


# Source types whose ``settings`` value carries a ``credential_id`` reference to
# an encrypted vault credential (``credentials`` table) instead of an inline
# secret. The other source types (pyats/mattermost/ise) use dedicated config
# services but follow the same ``credential_id`` contract.
_TOKEN_SOURCE_TYPES = frozenset({"nautobot"})


class SettingsService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self.repo = SettingsRepository(db)
        self._credentials = CredentialsService(db)

    # -- read -------------------------------------------------------------

    def _redact_source_token(self, key: str, value: dict[str, Any] | None) -> dict[str, Any]:
        """Public view of a token-source setting value.

        The inline secret never leaves the server; callers get
        ``token_configured`` plus the ``credential_id`` / ``credential_name``
        of the linked vault credential so the settings UI can pre-select it.
        """
        parsed = parse_source_key(key)
        raw = dict(value or {})
        if parsed is None or parsed[0] not in _TOKEN_SOURCE_TYPES:
            return raw
        credential_id = raw.get("credential_id")
        redacted = {k: v for k, v in raw.items() if k != "token"}
        redacted["token"] = ""
        redacted["token_configured"] = credential_id is not None
        redacted["credential_id"] = credential_id
        redacted["credential_name"] = self._credential_name(credential_id)
        return redacted

    def _credential_name(self, credential_id: Any) -> str | None:
        if not isinstance(credential_id, int):
            return None
        credential = self._credentials.get_credential_by_id(credential_id)
        return credential.get("name") if credential is not None else None

    def _to_response(self, setting: Setting) -> SettingResponse:
        return SettingResponse(
            id=setting.id,
            key=setting.key,
            value=self._redact_source_token(setting.key, setting.value),
            description=setting.description,
            created_at=setting.created_at,
            updated_at=setting.updated_at,
        )

    def list_settings(self, *, key_prefix: str | None = None) -> SettingListResponse:
        rows = self.repo.list_all(key_prefix=key_prefix)
        settings = [self._to_response(row) for row in rows]
        return SettingListResponse(settings=settings, total=len(settings))

    def get_setting(self, key: str) -> SettingResponse:
        setting = self.repo.get_by_key(key)
        if setting is None:
            raise NotFoundError(f"Setting '{key}' not found")
        return self._to_response(setting)

    def get_source_config(self, source_type: SourceType, source_id: str) -> dict[str, Any]:
        """Load a typed source setting and return its value with ``source_id`` set.

        Router-facing: raises domain errors directly, matching the 4
        call sites in routers/sources/git/ops.py that let it propagate
        uncaught to FastAPI's handler. Workflow-step executors must use
        ``get_source_config_for_step`` instead -- see its docstring.
        """
        source_id = source_id.strip()
        if not source_id:
            raise ValidationFailedError(f"{source_type}_source_id is required")
        try:
            setting_key = build_source_key(source_type, source_id)
        except ValueError as exc:
            raise ValidationFailedError(str(exc)) from exc
        setting = self.repo.get_by_key(setting_key)
        if setting is None:
            raise NotFoundError(f"{source_type.title()} source '{source_id}' not found in settings")
        value = dict(setting.value or {})
        if source_type in _TOKEN_SOURCE_TYPES:
            credential_id = value.pop("credential_id", None)
            if credential_id is not None:
                value["token"] = self._credentials.get_decrypted_password(credential_id)
        return {**value, "source_id": source_id}

    def get_source_config_for_step(self, source_type: SourceType, source_id: str) -> dict[str, Any]:
        """Worker-safe equivalent of ``get_source_config``.

        Workflow-step executors run in the Hatchet worker, not a FastAPI
        request, and must raise ``ValueError`` for configuration problems
        (doc/WORKFLOW-STEPS.md) rather than importing/catching
        ``fastapi.HTTPException`` -- see doc/FABLE-ANALYSIS.md 3.1.
        """
        try:
            return self.get_source_config(source_type, source_id)
        except DomainError as exc:
            raise SourceConfigError(str(exc.detail)) from exc

    # -- write ----------------------------------------------------------------

    def _assert_global_credential(self, credential_id: int) -> None:
        try:
            assert_global_credential(self._db, credential_id)
        except SourceCredentialError as exc:
            raise ValidationFailedError(str(exc)) from exc

    def create_setting(self, data: SettingCreate) -> SettingResponse:
        if self.repo.get_by_key(data.key) is not None:
            raise ConflictError(f"Setting '{data.key}' already exists")

        value, credential_id = self._normalize_source_value(data.key, data.value)
        parsed = parse_source_key(data.key)
        if parsed is not None and parsed[0] in _TOKEN_SOURCE_TYPES:
            if not isinstance(credential_id, int) or isinstance(credential_id, bool):
                raise ValidationFailedError("credential_id is required")
            self._assert_global_credential(credential_id)
            value["credential_id"] = credential_id

        logger.info("Creating setting key=%s", data.key)
        setting = self.repo.create(
            key=data.key,
            value=value,
            description=data.description,
        )
        return self._to_response(setting)

    def update_setting(self, key: str, data: SettingUpdate) -> SettingResponse:
        setting = self.repo.get_by_key(key)
        if setting is None:
            raise NotFoundError(f"Setting '{key}' not found")

        fields: dict = {}
        if data.value is not None:
            value, credential_id = self._normalize_source_value(key, dict(data.value))
            parsed = parse_source_key(key)
            if parsed is not None and parsed[0] in _TOKEN_SOURCE_TYPES:
                existing_credential_id = (setting.value or {}).get("credential_id")
                if isinstance(credential_id, int) and not isinstance(credential_id, bool):
                    self._assert_global_credential(credential_id)
                    value["credential_id"] = credential_id
                elif existing_credential_id is not None:
                    value["credential_id"] = existing_credential_id
                else:
                    raise ValidationFailedError("credential_id is required")
            fields["value"] = value
        if data.description is not None:
            fields["description"] = data.description

        if not fields:
            raise ValidationFailedError("No fields to update")

        logger.info("Updating setting key=%s", key)
        updated = self.repo.update(setting, fields)
        return self._to_response(updated)

    def delete_setting(self, key: str) -> None:
        setting = self.repo.get_by_key(key)
        if setting is None:
            raise NotFoundError(f"Setting '{key}' not found")
        logger.info("Deleting setting key=%s", key)
        self.repo.delete(setting)

    # -- helpers ------------------------------------------------------------

    def _normalize_source_value(self, key: str, value: dict) -> tuple[dict, Any]:
        """Validate a source setting value; return ``(value, credential_id)``.

        For token source types the inline ``token`` (if any is sent) is
        discarded -- secrets live only in the ``credentials`` table -- and the
        raw ``credential_id`` from the request is returned for the caller to
        validate and persist.
        """
        parsed = parse_source_key(key)
        if parsed is None:
            return value, None

        source_type, source_id = parsed
        value = dict(value)
        value.pop("token_configured", None)
        body_source_id = value.get("source_id")
        if isinstance(body_source_id, str) and body_source_id.strip():
            normalized_body_id = body_source_id.strip().lower()
            if normalized_body_id != source_id:
                raise ValidationFailedError(
                    f"source_id in value ('{normalized_body_id}') must match "
                    f"the key suffix ('{source_id}')"
                )

        validated = self._validate_source_url(source_type, value)

        credential_id: Any = None
        if source_type in _TOKEN_SOURCE_TYPES:
            validated.pop("token", None)
            credential_id = validated.pop("credential_id", None)

        result = ensure_value_source_id(validated, source_type=source_type, source_id=source_id)
        return result, credential_id

    @staticmethod
    def _validate_source_url(source_type: SourceType, value: dict) -> dict:
        """Validate outbound URLs for ISE/Nautobot (HTTP) source settings."""
        if source_type not in ("nautobot", "ise"):
            return value
        raw_url = value.get("url")
        if raw_url is None:
            return value
        try:
            safe_url = validate_outbound_http_url(str(raw_url), resolve_dns=True)
        except UnsafeURLError as exc:
            raise ValidationFailedError(str(exc)) from exc
        return {**value, "url": safe_url}
