"""Shared Nautobot source credential resolution for workflow steps.

One resolver, mirroring ``workflow_steps.common.mattermost_source`` and the
``*SourceConfigService.resolve_credentials`` pattern used by ISE / pyATS: the
non-secret connection settings (url, verify_ssl) live in the ``settings`` table
under ``sources.nautobot.<id>``; the API token lives in the encrypted
``credentials`` table and is referenced by ``credential_id``. Resolution goes
through ``SettingsService.get_source_config_for_step``, which turns that
``credential_id`` back into a decrypted token.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

import service_factory
from services.credentials.exceptions import (
    CredentialMissingFieldError,
    CredentialNotFoundError,
)
from services.nautobot.credentials import NautobotCredentials
from services.settings.exceptions import SourceConfigError
from services.settings.settings_service import SettingsService


def resolve_nautobot_credentials(
    db: Session, source_id: str, *, step_id: str
) -> NautobotCredentials:
    """Resolve a configured ``sources.nautobot.<id>`` source to API credentials.

    Raises ``ValueError`` for every configuration problem (missing/unknown
    source, source without a usable token or url) so the step contract's
    "ValueError = configuration error" holds — see doc/WORKFLOW-STEPS.md.
    """
    normalized = (source_id or "").strip()
    if not normalized:
        raise ValueError(f"{step_id}: nautobot_source_id is not configured")

    try:
        config = SettingsService(db).get_source_config_for_step("nautobot", normalized)
    except SourceConfigError as exc:
        raise ValueError(f"{step_id}: {exc}") from exc
    except (CredentialNotFoundError, CredentialMissingFieldError) as exc:
        raise ValueError(
            f"{step_id}: Nautobot source '{normalized}' credential is missing or has no token"
        ) from exc

    url = str(config.get("url") or "").strip()
    token = str(config.get("token") or "").strip()
    verify_ssl = bool(config.get("verify_ssl", True))
    if not url or not token:
        raise ValueError(
            f"{step_id}: Nautobot source '{normalized}' is missing url or token"
        )

    return service_factory.credentials_from_connection(url, token, verify_ssl=verify_ssl)
