"""Nautobot test-connection orchestration (form values or a saved source)."""

from __future__ import annotations

from sqlalchemy.orm import Session

import service_factory
from models.sources_nautobot import NautobotTestConnectionRequest, NautobotTestConnectionResponse
from services.credentials.source_credentials import SourceCredentialError, resolve_global_secret
from services.nautobot.common.exceptions import NautobotAPIError, NautobotValidationError
from services.settings.settings_service import SettingsService


async def test_nautobot_connection(
    request: NautobotTestConnectionRequest, db: Session
) -> NautobotTestConnectionResponse:
    """Resolve credentials (saved source or ad-hoc form values) and test connectivity.

    Raises ``NautobotValidationError`` / ``NautobotAPIError`` on failure — the
    caller (router) maps those to HTTP responses.
    """
    if request.source_id:
        config = SettingsService(db).get_source_config("nautobot", request.source_id)
        credentials = service_factory.credentials_from_connection(
            str(config.get("url") or ""),
            str(config.get("token") or ""),
            request.timeout,
            verify_ssl=config.get("verify_ssl", True),
        )
    else:
        try:
            _, token = resolve_global_secret(db, int(request.credential_id or 0))
        except SourceCredentialError as exc:
            raise NautobotValidationError(str(exc)) from exc
        credentials = service_factory.credentials_from_connection(
            (request.url or "").strip(),
            token,
            request.timeout,
            verify_ssl=request.verify_ssl,
        )
    nautobot = service_factory.get_nautobot_app_service()
    status_payload = await nautobot.test_connection(credentials)
    version = ""
    if isinstance(status_payload, dict):
        version = str(
            status_payload.get("nautobot-version") or status_payload.get("nautobot_version") or ""
        ).strip()
    message = f"Connection successful (Nautobot {version})" if version else "Connection successful"
    return NautobotTestConnectionResponse(success=True, message=message)


__all__ = ["test_nautobot_connection", "NautobotAPIError", "NautobotValidationError"]
